"""
Implementation of ``kb init``.

Creates ``$KANBAROO_CONFIG_DIR`` (defaulting to ``~/.kanbaroo``), runs
Alembic migrations to stand up the SQLite database, issues the first
personal API token, writes ``config.toml``, and prints the plaintext
token exactly once.

The command is idempotent-adjacent: running it twice against an existing
config.toml is an error unless ``--force`` is passed. ``--force`` issues
a fresh token and rewrites the config but never revokes existing tokens
in the database; the user is free to revoke old tokens later via
``kb token`` (milestone 10).
"""

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from sqlalchemy.orm import Session, sessionmaker

from kanbaroo_core import ActorType
from kanbaroo_core.auth import create_token
from kanbaroo_core.db import engine_for_url
from kanbaroo_core.migrations import upgrade_to_head

console = Console()


def _default_config_dir() -> Path:
    """
    Resolve the config directory from ``KANBAROO_CONFIG_DIR`` or fall
    back to ``$HOME/.kanbaroo``.
    """
    override = os.environ.get("KANBAROO_CONFIG_DIR")
    if override:
        return Path(override)
    return Path.home() / ".kanbaroo"


def _default_database_url(config_dir: Path) -> str:
    """
    Resolve the database URL from ``KANBAROO_DATABASE_URL`` or fall
    back to a SQLite file inside ``config_dir``.
    """
    override = os.environ.get("KANBAROO_DATABASE_URL")
    if override:
        return override
    return f"sqlite:///{config_dir / 'kanbaroo.db'}"


def _default_actor_id() -> str:
    """
    Default the initial token's actor id to the OS user, or
    ``"human"`` if ``$USER`` is not set (e.g. minimal containers).
    """
    return os.environ.get("USER") or "human"


def _render_config_toml(*, database_url: str, api_url: str, token: str) -> str:
    """
    Render the on-disk ``config.toml`` contents.

    Kept deliberately hand-crafted rather than pulling in a TOML writer:
    the file has three scalar keys and the escaping surface is tiny
    (double-quoted strings, backslash-escape internal quotes).
    """

    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    return (
        f'database_url = "{_escape(database_url)}"\n'
        f'api_url = "{_escape(api_url)}"\n'
        f'token = "{_escape(token)}"\n'
    )


def init(
    actor_id: str = typer.Option(
        None,
        "--actor-id",
        help="Label stamped on mutations from this token. Defaults to $USER.",
    ),
    name: str = typer.Option(
        "personal",
        "--name",
        help="Human-readable token name (shown in token lists).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing config.toml and issue a new token.",
    ),
) -> None:
    """
    Initialize Kanbaroo's local config, database, and first API token.
    """
    config_dir = _default_config_dir()
    database_url = _default_database_url(config_dir)
    resolved_actor_id = actor_id or _default_actor_id()

    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"

    if config_path.exists() and not force:
        console.print(
            f"[red]Error:[/red] {config_path} already exists. "
            "Re-run with [bold]--force[/bold] to overwrite the config "
            "and issue a new token."
        )
        raise typer.Exit(code=1)

    upgrade_to_head(database_url)

    engine = engine_for_url(database_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session: Session = factory()
    try:
        _, plaintext = create_token(
            session,
            actor_type=ActorType.HUMAN,
            actor_id=resolved_actor_id,
            name=name,
        )
        session.commit()
    finally:
        session.close()
        engine.dispose()

    api_url = "http://localhost:8080"
    config_path.write_text(
        _render_config_toml(
            database_url=database_url,
            api_url=api_url,
            token=plaintext,
        ),
        encoding="utf-8",
    )

    warning = (
        "[bold yellow]Save this token now. "
        "It will not be shown again.[/bold yellow]\n\n"
    )
    body = (
        f"[bold]Token:[/bold]        [green]{plaintext}[/green]\n"
        f"[bold]Config path:[/bold]  {config_path}\n"
        f"[bold]Database URL:[/bold] {database_url}\n"
        f"[bold]Actor:[/bold]        human / {resolved_actor_id}\n"
        f"[bold]Token name:[/bold]   {name}"
    )
    console.print(
        Panel.fit(
            warning + body,
            title="Kanbaroo initialized",
            border_style="green",
        )
    )
