# kanbaroo-plugin

A Claude Code plugin that bundles the agent skills for working with
[Kanbaroo](https://github.com/areese801/kanbaroo) — a kanban-style
issue tracker with a TUI, REST + WebSocket API, CLI, and MCP server.
The skills teach an outer Claude session how to drive the Kanbaroo MCP
tools and (optionally) tie them into a `cage-orchestrator` workflow
when trusty-cage is also installed.

## Skills shipped

- **`kanbaroo-workflow`** — the general workflow skill. Activates when
  the user references a Kanbaroo story by its human ID (e.g.
  `KAN-123`), asks about the board, or wants to capture follow-up
  work as new stories. Standalone; does not require trusty-cage.
- **`kanbaroo-cage-bridge`** — the integration layer between
  `cage-orchestrator` and Kanbaroo. Activates only when both the
  `kanbaroo` MCP server and the cage-orchestrator skill are active in
  the same session. Mirrors cage dispatches onto a Kanbaroo story:
  creates or attaches a story before launch, comments on progress,
  posts a summary on `tc export`, and captures revision instructions
  before they're sent to the cage's inbox. No-ops gracefully when
  Kanbaroo isn't configured.

## Prerequisites

1. **A running Kanbaroo instance.** The dogfood layout (single-user,
   docker-compose, host bind-mounted SQLite, nightly snapshots) is
   documented in
   [`docs/deployment-dogfood.md`](../../docs/deployment-dogfood.md).
2. **`kanbaroo-mcp` on `PATH`.** Install the meta package via pipx so
   every Kanbaroo binary (including the MCP server) is exposed:

   ```bash
   pipx install --include-deps 'kanbaroo[all]'
   ```

   `--include-deps` is load-bearing — without it pipx hides the
   sub-package binaries.
3. **Per-project wiring.** Run `kb project init` from the project's
   root. It creates a workspace, mints a per-project
   `actor_type=claude` token, and writes a project-root `.mcp.json`
   pointing at `kanbaroo-mcp --token-file <path>`. Restart Claude
   Code afterward so it picks up the new MCP entry.

## Install the plugin

The plugin lives inside the Kanbaroo monorepo for now. Symlink it
into Claude Code's plugin cache and restart:

```bash
# From the kanbaroo monorepo root, after cloning:
ln -s "$(pwd)/packages/kanbaroo-plugin" \
      ~/.claude/plugins/cache/kanbaroo-plugin
```

Then restart Claude Code. Both skills become available to every
session afterward.

The skills are passive — they do not run anything on install. Each
SKILL.md is matched against the user's message at session time, so
the workflow skill only fires when the user mentions Kanbaroo
concepts and the cage-bridge skill only fires when both Kanbaroo and
the cage-orchestrator are active.

## When each skill activates

| Skill | Activates when |
|-------|---------------|
| `kanbaroo-workflow` | The user references a Kanbaroo story human ID, asks about the board, or wants to create / comment / transition stories. |
| `kanbaroo-cage-bridge` | The session has both `mcp__kanbaroo__*` tools and the trusty-cage `cage-orchestrator` skill active, and a cage dispatch is about to be (or is being) driven. |

The bridge skill no-ops automatically on projects without the
Kanbaroo MCP wired up; cage-orchestrator runs unchanged in that case.

## Troubleshooting

- **Skills don't appear in a fresh Claude Code session.** Confirm the
  symlink resolves (`ls -l ~/.claude/plugins/cache/kanbaroo-plugin`
  should point at your monorepo's `packages/kanbaroo-plugin/`) and
  that Claude Code was fully restarted, not just reloaded.
- **The workflow skill fires but `mcp__kanbaroo__*` tools 404.**
  Confirm the project has a `.mcp.json` at its root with a
  `kanbaroo` entry and that the running Kanbaroo server is
  reachable at the URL listed in `--api-url`. `kb project init`
  writes both pieces in one shot.
- **The cage-bridge skill never fires even with both skills
  installed.** It is a deliberate no-op when Kanbaroo MCP isn't
  configured for the project. Re-run `kb project init` and restart
  Claude Code, or check `cage-orchestrator`'s own skill matching
  rules.

## Contents

```
packages/kanbaroo-plugin/
├── .claude-plugin/
│   └── plugin.json               # plugin manifest (name, version, repo)
├── skills/
│   ├── kanbaroo-workflow/
│   │   └── SKILL.md
│   └── kanbaroo-cage-bridge/
│       └── SKILL.md
└── README.md                     # this file
```
