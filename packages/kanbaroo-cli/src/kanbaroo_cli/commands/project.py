"""
Implementation of ``kb project init``.

A host-side ergonomics command that wires a project directory up to a
running Kanbaroo server in one shot:

* derives a workspace key and ``actor_id`` from the cwd basename,
* creates the workspace via the REST API (idempotent on 409),
* mints a fresh ``actor_type=claude`` token and writes the plaintext to
  ``~/.kanbaroo/tokens/<actor-id>`` at mode ``0600``,
* writes a project-root ``.mcp.json`` referencing
  ``kanbaroo-mcp --token-file <path>`` so the outer Claude Code picks
  it up on the next launch.

The command is deliberately conservative: ``--dry-run`` writes nothing,
``--force`` is required to overwrite a token file or ``.mcp.json``, and
``--json`` skips every interactive confirm so it can be driven by
automation.
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer

from kanbaroo_cli.client import ApiError, ApiRequestError
from kanbaroo_cli.commands.token import _write_token_file
from kanbaroo_cli.config import CliConfig, default_config_dir
from kanbaroo_cli.context import build_client, require_config
from kanbaroo_cli.rendering import (
    print_json,
    render_api_error,
    stderr_console,
    stdout_console,
)

app = typer.Typer(
    name="project",
    help="Project-scoped helpers for wiring a directory to Kanbaroo.",
    no_args_is_help=True,
)


_WORKSPACE_KEY_MAX_LEN = 8


@dataclass
class _PlanError:
    """
    A single failure surfaced by ``kb project init``.

    ``code`` is a stable machine-readable identifier the ``--json`` path
    emits verbatim; ``message`` is the human-readable companion shown to
    interactive users.
    """

    code: str
    message: str


@dataclass
class _ProjectPlan:
    """
    Resolved view of what ``kb project init`` would do, ready to render
    in dry-run mode or execute live.
    """

    workspace_key: str
    workspace_name: str
    actor_id: str
    token_name: str
    api_url: str
    project_root: Path
    token_file: Path
    mcp_json_path: Path
    mcp_command: str
    next_steps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    errors: list[_PlanError] = field(default_factory=list)


def _slug_from_basename(basename: str) -> str:
    """
    Lowercase ``basename`` and replace any run of non-alphanumeric
    characters with a single ``-``, trimming leading/trailing
    separators.

    Empty or all-non-alphanumeric inputs collapse to ``project`` so the
    final ``actor_id`` always has a useful tail. Unicode characters that
    do not match ``[a-z0-9]`` after lowercasing are treated as
    separators.
    """
    lowered = basename.lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return cleaned or "project"


def _key_from_basename(basename: str) -> str:
    """
    Uppercase ``basename`` and keep only ``[A-Z0-9]`` characters,
    truncating to :data:`_WORKSPACE_KEY_MAX_LEN`.

    Returns ``"PROJECT"`` (already truncated to fit) when the input
    yields no usable characters; this keeps the derivation total without
    handing the server an empty string.
    """
    upper = basename.upper()
    filtered = re.sub(r"[^A-Z0-9]+", "", upper)
    if not filtered:
        filtered = "PROJECT"
    return filtered[:_WORKSPACE_KEY_MAX_LEN]


def _name_from_basename(basename: str) -> str:
    """
    Title-case ``basename`` for use as the workspace display name.

    Splits on ``[-_\\s.]`` so directories like ``diff-donkey`` become
    ``Diff Donkey``. Falls back to ``"Project"`` when no usable tokens
    survive the split.
    """
    pieces = [piece for piece in re.split(r"[-_\s.]+", basename) if piece]
    if not pieces:
        return "Project"
    return " ".join(piece[:1].upper() + piece[1:] for piece in pieces)


def _verify_mcp_json_support() -> str | None:
    """
    Best-effort probe for project-root ``.mcp.json`` support in the
    user's Claude Code install.

    Returns ``None`` when we can confirm support (either the user's
    global ``CLAUDE.md`` mentions ``.mcp.json`` or the ``claude``
    binary is on ``$PATH`` and ``claude --version`` exits cleanly).
    Otherwise returns a human-readable note the caller should print so
    the user knows to fall back to manually editing ``~/.claude.json``.
    """
    home_claude_md = Path.home() / ".claude" / "CLAUDE.md"
    if home_claude_md.is_file():
        try:
            text = home_claude_md.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        if ".mcp.json" in text:
            return None

    if shutil.which("claude"):
        try:
            result = subprocess.run(
                ["claude", "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is not None and result.returncode == 0:
            return None

    return (
        "Could not verify that Claude Code honors project-root "
        ".mcp.json. Proceeding anyway; if the MCP entry doesn't appear "
        "in your next Claude Code session, add it manually to "
        "~/.claude.json."
    )


def _build_plan(
    *,
    cwd: Path,
    api_url: str,
    key_override: str | None,
    name_override: str | None,
    actor_id_override: str | None,
    token_name_override: str | None,
    config_dir: Path,
) -> _ProjectPlan:
    """
    Resolve the per-project values that ``kb project init`` will act on.

    Pure: takes every input as an argument and returns a fully populated
    :class:`_ProjectPlan` without touching the filesystem (beyond the
    cwd basename it was passed). The caller is responsible for the
    ``--dry-run`` vs live distinction.
    """
    basename = cwd.name or "project"
    workspace_key = key_override or _key_from_basename(basename)
    workspace_name = name_override or _name_from_basename(basename)
    actor_id = actor_id_override or f"claude-{_slug_from_basename(basename)}"
    token_name = token_name_override or f"{workspace_name} outer Claude"
    token_file = (config_dir / "tokens" / actor_id).resolve()
    mcp_json_path = (cwd / ".mcp.json").resolve()
    return _ProjectPlan(
        workspace_key=workspace_key,
        workspace_name=workspace_name,
        actor_id=actor_id,
        token_name=token_name,
        api_url=api_url,
        project_root=cwd.resolve(),
        token_file=token_file,
        mcp_json_path=mcp_json_path,
        mcp_command="kanbaroo-mcp",
    )


def _render_mcp_json(plan: _ProjectPlan) -> str:
    """
    Render the ``.mcp.json`` body referencing the freshly-minted token
    file.

    The path is absolute so external tools that read the JSON do not
    need to expand ``~`` themselves. The output is pretty-printed with
    a trailing newline so it diffs cleanly when checked into version
    control alongside the rest of the project.
    """
    body = {
        "mcpServers": {
            "kanbaroo": {
                "type": "stdio",
                "command": plan.mcp_command,
                "args": [
                    "--api-url",
                    plan.api_url,
                    "--token-file",
                    str(plan.token_file),
                ],
            }
        }
    }
    return json.dumps(body, indent=2) + "\n"


def _ensure_token_file_writable(
    plan: _ProjectPlan,
    *,
    force: bool,
    interactive: bool,
    json_mode: bool,
) -> _PlanError | None:
    """
    Decide whether the token file may be written.

    Returns a :class:`_PlanError` when the existing file blocks the
    write (and ``--force`` was not passed); returns ``None`` when the
    write is allowed (either the file is absent, ``--force`` is set, or
    the interactive user confirmed the overwrite).
    """
    if not plan.token_file.exists():
        return None
    if force:
        return None
    if json_mode or not interactive:
        return _PlanError(
            code="token_file_exists",
            message=(
                f"token file {plan.token_file} already exists; pass "
                "--force to overwrite."
            ),
        )
    confirmed = typer.confirm(
        f"Token file {plan.token_file} already exists. Overwrite?",
        default=False,
    )
    if confirmed:
        return None
    return _PlanError(
        code="token_file_exists",
        message=f"token file {plan.token_file} already exists; aborted.",
    )


def _ensure_mcp_json_writable(
    plan: _ProjectPlan,
    *,
    force: bool,
    interactive: bool,
    json_mode: bool,
) -> _PlanError | None:
    """
    Decide whether ``.mcp.json`` may be written.

    Mirrors :func:`_ensure_token_file_writable` but for the
    project-root MCP config; the same ``--force`` / interactive prompt
    rules apply.
    """
    if not plan.mcp_json_path.exists():
        return None
    if force:
        return None
    if json_mode or not interactive:
        return _PlanError(
            code="mcp_json_exists",
            message=(
                f"{plan.mcp_json_path} already exists; pass --force to overwrite."
            ),
        )
    confirmed = typer.confirm(
        f"{plan.mcp_json_path} already exists. Overwrite?",
        default=False,
    )
    if confirmed:
        return None
    return _PlanError(
        code="mcp_json_exists",
        message=f"{plan.mcp_json_path} already exists; aborted.",
    )


def _emit_plan_panel(plan: _ProjectPlan) -> None:
    """
    Print the resolved plan as a Rich-flavored summary on stdout so an
    interactive user can confirm the derivations before any state
    changes happen.
    """
    stdout_console.print("[bold]kb project init plan[/bold]")
    stdout_console.print(f"  workspace key:    [cyan]{plan.workspace_key}[/cyan]")
    stdout_console.print(f"  workspace name:   {plan.workspace_name}")
    stdout_console.print(f"  actor id:         [cyan]{plan.actor_id}[/cyan]")
    stdout_console.print(f"  token name:       {plan.token_name}")
    stdout_console.print(f"  api url:          {plan.api_url}")
    stdout_console.print(f"  token file:       {plan.token_file}")
    stdout_console.print(f"  .mcp.json target: {plan.mcp_json_path}")


def _post_init_steps(plan: _ProjectPlan) -> list[str]:
    """
    Build the post-init checklist printed to the terminal (or returned
    in ``--json`` mode under ``next_steps``).
    """
    return [
        "Restart Claude Code in this project for the kanbaroo MCP entry to activate.",
        f"Token file is at {plan.token_file} (mode 0600). Keep it out of git.",
        f"Workspace {plan.workspace_key} is live at "
        f"{plan.api_url.rstrip('/')}/ui (sign in with the new token).",
    ]


def _create_workspace(
    config: CliConfig,
    plan: _ProjectPlan,
) -> tuple[str, str | None]:
    """
    Call ``POST /api/v1/workspaces`` for the planned workspace.

    Returns ``(status, conflict_message)`` where ``status`` is
    ``"created"`` on a successful 2xx, ``"exists"`` when the server
    returned 409 (already exists), or ``"failed"`` when an unexpected
    HTTP error fired. ``conflict_message`` is the error envelope body
    when the call hit a non-409 failure so the caller can surface it.
    """
    payload: dict[str, object] = {
        "key": plan.workspace_key,
        "name": plan.workspace_name,
    }
    with build_client(config) as client:
        try:
            client.post("/workspaces", json=payload)
        except ApiRequestError as exc:
            if exc.status_code == 409:
                return "exists", None
            return "failed", f"{exc.code}: {exc.message}"
        except ApiError as exc:
            return "failed", str(exc)
    return "created", None


def _mint_token(config: CliConfig, plan: _ProjectPlan) -> str:
    """
    Call ``POST /api/v1/tokens`` for the planned ``actor_type=claude``
    token and return the freshly-minted plaintext.

    Raises :class:`ApiError` on transport failure or an unexpected
    status; the caller translates that into a clean exit.
    """
    body: dict[str, Any] = {
        "name": plan.token_name,
        "actor_type": "claude",
        "actor_id": plan.actor_id,
    }
    with build_client(config) as client:
        response = client.post("/tokens", json=body)
        return str(response.json()["plaintext"])


def _emit_json_result(
    *,
    plan: _ProjectPlan,
    workspace_status: str,
    token_status: str,
    mcp_json_status: str,
    notes: list[str],
    errors: list[_PlanError],
    dry_run: bool,
) -> None:
    """
    Pretty-print the structured result blob for ``--json`` mode.

    Keeps the schema flat enough that downstream tools can grep for
    ``status`` and ``errors[].code`` without needing a parser. The
    ``next_steps`` array doubles as the human-readable post-init
    checklist.
    """
    payload = {
        "status": "ok" if not errors else "error",
        "dry_run": dry_run,
        "workspace": {
            "key": plan.workspace_key,
            "name": plan.workspace_name,
            "status": workspace_status,
        },
        "token": {
            "actor_id": plan.actor_id,
            "name": plan.token_name,
            "file": str(plan.token_file),
            "status": token_status,
        },
        "mcp_json": {
            "path": str(plan.mcp_json_path),
            "status": mcp_json_status,
        },
        "api_url": plan.api_url,
        "notes": notes,
        "next_steps": _post_init_steps(plan),
        "errors": [{"code": err.code, "message": err.message} for err in errors],
    }
    print_json(payload)


@app.command("init")
def project_init(
    key: str | None = typer.Option(
        None,
        "--key",
        help=(
            "Workspace key. Defaults to the cwd basename uppercased, "
            "non-alphanumerics stripped, truncated to 8 chars."
        ),
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        help=("Workspace display name. Defaults to the cwd basename title-cased."),
    ),
    actor_id: str | None = typer.Option(
        None,
        "--actor-id",
        help=(
            "Per-project actor id stamped on every mutation made via "
            "the new MCP token. Defaults to claude-<slug-of-cwd>."
        ),
    ),
    token_name: str | None = typer.Option(
        None,
        "--token-name",
        help=(
            "Display name for the new claude-typed token. Defaults to "
            "'<workspace name> outer Claude'."
        ),
    ),
    api_url_override: str | None = typer.Option(
        None,
        "--api-url",
        help=(
            "Override the configured api_url for the workspace + token "
            "calls and for the .mcp.json args."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the resolved plan and exit without making changes.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=("Overwrite an existing token file or .mcp.json without prompting."),
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit a structured JSON result. Skips interactive confirms; "
            "blocking conditions become non-zero exits with a clear "
            "errors[] payload."
        ),
    ),
) -> None:
    """
    Wire the current directory up to a running Kanbaroo server.

    Creates (or recognises) a workspace, mints a per-project
    ``actor_type=claude`` token saved to
    ``~/.kanbaroo/tokens/<actor-id>``, and writes a ``.mcp.json`` that
    points the outer Claude Code at the new token. Every step honors
    ``--dry-run`` and ``--force``; ``--json`` is the automation-friendly
    output mode.
    """
    config = require_config()
    api_url = api_url_override or config.api_url
    if api_url_override and api_url_override != config.api_url:
        config = dataclasses.replace(config, api_url=api_url_override)
    plan = _build_plan(
        cwd=Path.cwd(),
        api_url=api_url,
        key_override=key,
        name_override=name,
        actor_id_override=actor_id,
        token_name_override=token_name,
        config_dir=default_config_dir(),
    )

    interactive = not as_json and not dry_run
    notes: list[str] = []
    errors: list[_PlanError] = []

    mcp_note = _verify_mcp_json_support()
    if mcp_note is not None:
        notes.append(mcp_note)
        if not as_json:
            stderr_console.print(f"[yellow]Note:[/yellow] {mcp_note}")

    if not as_json:
        _emit_plan_panel(plan)

    if interactive:
        confirmed = typer.confirm("Continue?", default=True)
        if not confirmed:
            stdout_console.print("aborted.")
            raise typer.Exit(code=0)

    if dry_run:
        if as_json:
            _emit_json_result(
                plan=plan,
                workspace_status="planned",
                token_status="planned",
                mcp_json_status="planned",
                notes=notes,
                errors=[],
                dry_run=True,
            )
        else:
            stdout_console.print(
                "[bold]--dry-run[/bold]: no workspace, token, or .mcp.json was created."
            )
            for step in _post_init_steps(plan):
                stdout_console.print(f"  next: {step}")
        return

    token_block = _ensure_token_file_writable(
        plan,
        force=force,
        interactive=interactive,
        json_mode=as_json,
    )
    if token_block is not None:
        errors.append(token_block)
    mcp_block = _ensure_mcp_json_writable(
        plan,
        force=force,
        interactive=interactive,
        json_mode=as_json,
    )
    if mcp_block is not None:
        errors.append(mcp_block)
    if errors:
        if as_json:
            _emit_json_result(
                plan=plan,
                workspace_status="skipped",
                token_status="skipped",
                mcp_json_status="skipped",
                notes=notes,
                errors=errors,
                dry_run=False,
            )
        else:
            for err in errors:
                stderr_console.print(f"[red]Error[/red] ({err.code}): {err.message}")
        raise typer.Exit(code=1)

    workspace_status, workspace_message = _create_workspace(config, plan)
    if workspace_status == "failed":
        message = workspace_message or "workspace create failed"
        if as_json:
            errors.append(_PlanError(code="workspace_failed", message=message))
            _emit_json_result(
                plan=plan,
                workspace_status="failed",
                token_status="skipped",
                mcp_json_status="skipped",
                notes=notes,
                errors=errors,
                dry_run=False,
            )
        else:
            stderr_console.print(f"[red]workspace create failed:[/red] {message}")
        raise typer.Exit(code=1)
    if workspace_status == "exists" and not as_json:
        stdout_console.print(
            f"workspace [bold]{plan.workspace_key}[/bold] already exists, skipping."
        )

    try:
        plaintext = _mint_token(config, plan)
    except ApiError as exc:
        message = str(exc)
        if as_json:
            errors.append(_PlanError(code="token_mint_failed", message=message))
            _emit_json_result(
                plan=plan,
                workspace_status=workspace_status,
                token_status="failed",
                mcp_json_status="skipped",
                notes=notes,
                errors=errors,
                dry_run=False,
            )
        else:
            render_api_error(exc)
        raise typer.Exit(code=1) from exc

    _write_token_file(plan.token_file, plaintext)
    plan.mcp_json_path.write_text(_render_mcp_json(plan), encoding="utf-8")

    if as_json:
        _emit_json_result(
            plan=plan,
            workspace_status=workspace_status,
            token_status="written",
            mcp_json_status="written",
            notes=notes,
            errors=[],
            dry_run=False,
        )
        return

    stdout_console.print(f"[green]wrote token[/green] {plan.token_file} (mode 0600)")
    stdout_console.print(f"[green]wrote[/green] {plan.mcp_json_path}")
    stdout_console.print()
    stdout_console.print("[bold]Next steps:[/bold]")
    for step in _post_init_steps(plan):
        stdout_console.print(f"  - {step}")


__all__ = [
    "app",
    "project_init",
]
