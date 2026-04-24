"""
Kanbaroo CLI entry point.

Exposes the root Typer app and mounts every sub-app defined in
``kanbaroo_cli.commands``. The root callback is a no-op so Typer
always treats registered entries as subcommands; this mirrors the
pattern established when only ``kb init`` existed and keeps the help
output consistent as new commands arrive.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

import typer

from kanbaroo_cli.commands import audit as audit_command
from kanbaroo_cli.commands import backup as backup_command
from kanbaroo_cli.commands import epic as epic_command
from kanbaroo_cli.commands import export as export_command
from kanbaroo_cli.commands import init as init_command
from kanbaroo_cli.commands import server as server_command
from kanbaroo_cli.commands import story as story_command
from kanbaroo_cli.commands import tag as tag_command
from kanbaroo_cli.commands import token as token_command
from kanbaroo_cli.commands import workspace as workspace_command
from kanbaroo_cli.rendering import stdout_console

app = typer.Typer(
    name="kanbaroo",
    help="Kanbaroo: a kanban-style issue tracker for terminals and AI agents.",
    no_args_is_help=True,
    add_completion=False,
)


def _installed_version() -> str:
    """
    Return the installed ``kanbaroo-cli`` version, or ``"unknown"`` when
    the package is not installed (e.g. running directly from source
    without an editable install).
    """
    try:
        return _pkg_version("kanbaroo-cli")
    except PackageNotFoundError:
        return "unknown"


def _version_callback(value: bool) -> None:
    """
    Eager Typer option callback for ``--version``. Prints the installed
    version and exits cleanly before any subcommand runs.
    """
    if value:
        stdout_console.print(_installed_version())
        raise typer.Exit(code=0)


@app.callback()
def _root(
    _version: bool = typer.Option(
        False,
        "--version",
        help="Print the installed kanbaroo-cli version and exit.",
        is_eager=True,
        callback=_version_callback,
    ),
) -> None:
    """
    Root callback. Exists only so Typer treats registered commands as
    subcommands; it also wires the ``--version`` option.
    """


@app.command(
    name="version",
    help="Print the installed kanbaroo-cli version.",
)
def version_command() -> None:
    """
    Print the installed kanbaroo-cli version. Mirrors ``kb --version``.
    """
    stdout_console.print(_installed_version())


app.command(
    name="init",
    help="Initialise the Kanbaroo config directory, database, and first token.",
)(init_command.init)

app.command(
    name="audit",
    help="Show the audit history for a story or epic.",
)(audit_command.audit_command)

app.command(
    name="export",
    help="Download an export archive for a workspace.",
)(export_command.export_command)

app.command(
    name="backup",
    help="Copy the configured SQLite database file to a timestamped path.",
)(backup_command.backup_command)

app.add_typer(workspace_command.app, name="workspace")
app.add_typer(story_command.app, name="story")
app.add_typer(epic_command.app, name="epic")
app.add_typer(tag_command.app, name="tag")
app.add_typer(token_command.app, name="token")
app.add_typer(server_command.app, name="server")


if __name__ == "__main__":
    app()
