# Dogfood deployment guide

This document describes the recommended layout for running Kanbaroo as
your own daily driver — the "dogfood" instance that the project's
maintainer uses to track the project's own work. The goal is a setup
where your dotfiles are safe to publish, every project gets its own
attributed token, and the database lives somewhere your normal OS
backup tooling can find it.

The recipes below work on macOS, Linux, and Windows. Where the
filesystem layout differs by OS, the per-platform default is called
out and `$KANBAROO_DATA_DIR` is the universal override knob.

## Why "dogfood"?

A dogfood instance is the long-lived, single-user Kanbaroo install
that you actually use to track real work. It is distinct from:

- Throwaway `kb init` setups that live alongside a feature branch.
- The Docker compose file inside the repo that runs the API in a
  container against a host bind-mount.
- A team-shared instance running on a server somewhere.

The word matters because the trade-offs differ. A dogfood instance:

- Has to survive container rebuilds and laptop reboots.
- Is something you want backed up the same way you back up your
  documents.
- Issues a separate, attributed token for every project so the audit
  log stays useful.
- Keeps `config.toml` in your dotfiles repo without leaking tokens.

## Filesystem layout

The CLI and dotfiles live under `~/.kanbaroo/` regardless of OS:

```
~/.kanbaroo/
├── config.toml                       # tracked in dotfiles
├── tokens/                           # gitignored
│   ├── claude-projectA
│   ├── claude-projectB
│   └── personal
└── backups/                          # gitignored
    ├── kanbaroo-2026-04-29T03-00-00Z.db
    └── ...
```

The SQLite database lives outside dotfiles entirely, in the platform's
canonical user-data location. `kb server start` resolves a default for
your OS and exports it to the docker-compose subprocess as
`$KANBAROO_DATA_DIR`; you can override it on any platform by
exporting the variable yourself.

| Platform | Default data dir |
|----------|------------------|
| macOS | `~/Library/Application Support/Kanbaroo/` |
| Linux | `${XDG_DATA_HOME:-$HOME/.local/share}/kanbaroo/` |
| Windows | `%LOCALAPPDATA%\Kanbaroo\` (fallback `%USERPROFILE%\AppData\Local\Kanbaroo\`) |
| Other (BSDs, etc.) | `$HOME/.local/share/kanbaroo/` |

The split is deliberate:

- `config.toml` is small, non-sensitive, and version-controlled with
  the rest of your dotfiles.
- The `tokens/` directory holds plaintext bearer tokens, one per
  actor. Each file is mode `0600` and is gitignored.
- `backups/` holds nightly snapshots produced by `kb backup`.
- The database lives in the OS-canonical user-data directory so the
  platform's normal backup tooling (Time Machine on macOS, the
  XDG-style data dir on Linux, File History on Windows) covers it
  without extra configuration.

To move the database elsewhere — encrypted volume, NAS mount, CI
sandbox — export `KANBAROO_DATA_DIR` to point at the new location
before invoking `kb server start`. The compose file requires the
variable; if it ever gets unset and the default cannot be resolved,
docker-compose errors out cleanly with the message defined in
`docker-compose.yml` rather than silently writing to the wrong place.

## Sample `~/.kanbaroo/config.toml`

```toml
api_url = "http://localhost:8080"

# Resolved at runtime. The file at this path holds the bearer token
# for the *outer* CLI/TUI process. Per-project tokens (see below) are
# selected by setting $KANBAROO_TOKEN in that project's environment.
token_file = "~/.kanbaroo/tokens/personal"

# Optional: only needed for `kb backup`, which reads the SQLite file
# directly. Inside the container this is overridden by
# $KANBAROO_DATABASE_URL. Adjust the absolute path to match your OS:
#   macOS:   sqlite:////Users/you/Library/Application Support/Kanbaroo/kanbaroo.db
#   Linux:   sqlite:////home/you/.local/share/kanbaroo/kanbaroo.db
#   Windows: sqlite:///C:/Users/you/AppData/Local/Kanbaroo/kanbaroo.db
database_url = "sqlite:////Users/you/Library/Application Support/Kanbaroo/kanbaroo.db"
```

`token_file` accepts `~`-relative paths and trims trailing whitespace,
so it is safe to write tokens with a final newline.

## Sample dotfiles `.gitignore`

If you keep `~/.kanbaroo/` inside a dotfiles repo, ignore the secret
bits:

```gitignore
# Kanbaroo
.kanbaroo/tokens/
.kanbaroo/backups/
# Legacy: pre-v0.3.0 layouts kept the SQLite DB next to config.toml.
.kanbaroo/*.db
```

Adjust the prefix to match wherever your dotfiles repo roots
`~/.kanbaroo/`.

## First-time per-project setup

`kb project init` is the recommended one-shot for wiring a project
directory up to a running Kanbaroo server. Run it from inside the
project's root:

```bash
cd ~/projects/diff-donkey
kb project init
```

It derives sensible defaults from the cwd basename, asks for one
confirmation, and then:

1. creates (or recognises, on 409) the workspace,
2. mints a fresh `actor_type=claude` token and writes the plaintext
   to `~/.kanbaroo/tokens/<actor-id>` at mode `0600`, and
3. writes a project-root `.mcp.json` that points the outer Claude Code
   at the new token via `kanbaroo-mcp --token-file <absolute path>`.

The resulting `.mcp.json` looks like:

```json
{
  "mcpServers": {
    "kanbaroo": {
      "type": "stdio",
      "command": "kanbaroo-mcp",
      "args": [
        "--api-url",
        "http://localhost:8080",
        "--token-file",
        "/home/you/.kanbaroo/tokens/claude-diff-donkey"
      ]
    }
  }
}
```

Useful flags:

- `--key`, `--name`, `--actor-id`, `--token-name`: override any of the
  derived defaults. Without these, `~/projects/diff-donkey` becomes
  workspace key `DIFFDONK`, name `Diff Donkey`, actor id
  `claude-diff-donkey`.
- `--api-url`: override the configured `api_url` for the workspace +
  token calls and for the rendered `.mcp.json`.
- `--dry-run`: print the resolved plan without writing anything.
- `--force`: overwrite an existing token file or `.mcp.json` without
  prompting.
- `--json`: emit a structured result blob (with stable `errors[].code`
  values like `token_file_exists`) for automation.

Restart Claude Code in the project after the command finishes so the
new MCP entry activates.

## Per-project tokens (manual recipe)

If `kb project init` doesn't fit your setup, the equivalent manual
recipe is:

```bash
kb token create \
  --actor-type claude \
  --actor-id claude-<project-slug> \
  --name "<project> outer Claude" \
  --output-file ~/.kanbaroo/tokens/claude-<project-slug>
```

`--output-file` writes the plaintext to the path with mode `0600` and
creates parent directories on the fly. The token also still echoes to
stdout once — the file is a convenience copy, not the only copy.

The MCP server's `--token-file` flag can then reference the file
directly, with no shell-init plumbing required:

```json
{
  "mcpServers": {
    "kanbaroo": {
      "command": "kanbaroo-mcp",
      "args": [
        "--api-url", "http://localhost:8080",
        "--token-file", "/home/you/.kanbaroo/tokens/claude-projectA"
      ]
    }
  }
}
```

If you prefer the env-var pattern, `--token-env KANBAROO_MCP_TOKEN`
still works as long as the project's launching shell exports the
variable before Claude Code starts.

## Container bind-mount

`docker-compose.yml` bind-mounts the host directory referenced by
`$KANBAROO_DATA_DIR` into the container as `/data`:

```yaml
volumes:
  - ${KANBAROO_DATA_DIR:?KANBAROO_DATA_DIR is required - see docs/deployment-dogfood.md}:/data
```

The `:?...` form makes docker-compose error out cleanly if the
variable is somehow unset. In normal use you will never see that
error: `kb server start` exports a platform-appropriate default
before invoking `docker compose up -d`. To override, export the
variable yourself:

```bash
# macOS / Linux / WSL — adjust to taste
export KANBAROO_DATA_DIR="$HOME/.kanbaroo-data"
kb server start
```

```powershell
# Windows PowerShell
$env:KANBAROO_DATA_DIR = "$env:USERPROFILE\Kanbaroo-data"
kb server start
```

The container still uses
`KANBAROO_DATABASE_URL=sqlite:////data/kanbaroo.db` internally; the
four-slash form is the absolute path inside the container. Because
the host directory is the source of truth, the database survives any
`docker compose down`, `docker compose up -d`, or image rebuild.

If you are upgrading from a previous version that used the
`kanbaroo-data` named volume, copy the database out manually before
switching compose files:

```bash
docker compose cp kanbaroo-api:/data/kanbaroo.db \
  "$KANBAROO_DATA_DIR/kanbaroo.db"
```

There is no automated migration script — the named volume only
exists on developer laptops, the move is one-time, and inspection by
hand is cheaper than maintaining a script.

## Nightly snapshots

Kanbaroo ships a `kb backup` command that copies the SQLite file to a
timestamped path. Wrap it in a small platform-specific script and
schedule the script via your OS's normal scheduler.

### Wrapper script

`~/.kanbaroo/scripts/snapshot.sh` (macOS / Linux):

```bash
#!/usr/bin/env bash
set -euo pipefail

readonly _BACKUP_DIR="${HOME}/.kanbaroo/backups"

mkdir -p "${_BACKUP_DIR}"

# Take the snapshot. `kb backup` writes a kanbaroo-<UTC-ISO>.db file
# into --output (the directory must already exist).
kb backup --output "${_BACKUP_DIR}"

# Prune snapshots older than 14 days. -mtime +14 means strictly
# greater than 14 days; -delete is in-process so we do not need find
# to spawn rm.
find "${_BACKUP_DIR}" -name '*.db' -type f -mtime +14 -delete
```

Make it executable: `chmod +x ~/.kanbaroo/scripts/snapshot.sh`.

### macOS launchd plist

`~/Library/LaunchAgents/com.kanbaroo.snapshot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.kanbaroo.snapshot</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>/Users/you/.kanbaroo/scripts/snapshot.sh</string>
  </array>

  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>3</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>

  <key>StandardOutPath</key>
  <string>/Users/you/.kanbaroo/backups/snapshot.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/you/.kanbaroo/backups/snapshot.log</string>
</dict>
</plist>
```

Install (as your user, not as root):

```bash
launchctl load ~/Library/LaunchAgents/com.kanbaroo.snapshot.plist
```

Replace `/Users/you/` with your actual home directory; launchd plists
do not expand `~` or `$HOME`. The `-lc` invocation runs under your
login shell so `kb` is on `PATH`.

To stop the schedule:

```bash
launchctl unload ~/Library/LaunchAgents/com.kanbaroo.snapshot.plist
```

### Linux: systemd timer or cron

A drop-in systemd user timer works well. Sample
`~/.config/systemd/user/kanbaroo-snapshot.{service,timer}`:

```ini
# kanbaroo-snapshot.service
[Unit]
Description=Kanbaroo nightly snapshot

[Service]
Type=oneshot
ExecStart=%h/.kanbaroo/scripts/snapshot.sh
```

```ini
# kanbaroo-snapshot.timer
[Unit]
Description=Run the Kanbaroo snapshot at 03:00 nightly

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable: `systemctl --user enable --now kanbaroo-snapshot.timer`. A
plain crontab line (`0 3 * * * $HOME/.kanbaroo/scripts/snapshot.sh`)
works too if you do not have systemd user services available.

### Windows: Task Scheduler

Translate the wrapper script to PowerShell
(`%USERPROFILE%\.kanbaroo\scripts\snapshot.ps1`) and register a Task
Scheduler entry that runs it nightly. The pruning step uses
`Get-ChildItem -Recurse -Filter '*.db' | Where-Object LastWriteTime
-lt (Get-Date).AddDays(-14) | Remove-Item -Force`.

## Restore from a snapshot

Snapshots are plain SQLite files. To roll back:

1. Stop the API container so nothing has the database open:

   ```bash
   docker compose down
   ```

2. Copy the desired snapshot over the live database:

   ```bash
   cp "$HOME/.kanbaroo/backups/kanbaroo-2026-04-29T03-00-00Z.db" \
      "$KANBAROO_DATA_DIR/kanbaroo.db"
   ```

3. Bring the stack back up:

   ```bash
   docker compose up -d
   ```

The container reads the database from the same bind-mount, so the
restored file is picked up immediately. No migrations are required:
snapshots and the live database share the same schema unless you
restored across a Kanbaroo major version, in which case run
`alembic upgrade head` inside the container before pointing clients
at it.

## Installing the Kanbaroo plugin

Once your Kanbaroo instance is running and a project is wired up via
`kb project init`, install the `kanbaroo-plugin` so an outer Claude
Code session knows how to drive the MCP tools. The plugin ships two
skills: the general `kanbaroo-workflow` skill and the
`kanbaroo-cage-bridge` skill that ties cage-orchestrator dispatches
to Kanbaroo stories. Both ship together — installing the plugin
makes both available.

The plugin lives inside this monorepo at
`packages/kanbaroo-plugin/`. The dogfood install pattern is a
symlink into Claude Code's plugin cache:

```bash
# From the kanbaroo monorepo root (after cloning):
ln -s "$(pwd)/packages/kanbaroo-plugin" \
      ~/.claude/plugins/cache/kanbaroo-plugin
```

Restart Claude Code afterward. Both skills become available in every
new session. They are passive: matching is driven by the SKILL.md
descriptions, so the workflow skill only fires when you mention
Kanbaroo concepts and the cage-bridge skill only fires when both
Kanbaroo and trusty-cage's `cage-orchestrator` are active in the
same session. On projects without the Kanbaroo MCP wired up, the
cage-bridge no-ops and `cage-orchestrator` runs unchanged.

To uninstall, remove the symlink:

```bash
rm ~/.claude/plugins/cache/kanbaroo-plugin
```

Then restart Claude Code.
