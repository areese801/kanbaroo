"""
Kanberoo CLI entry point.

Exposes the root Typer app and mounts every sub-app defined in
``kanberoo_cli.commands``. The root callback is a no-op so Typer
always treats registered entries as subcommands; this mirrors the
pattern established when only ``kb init`` existed and keeps the help
output consistent as new commands arrive.
"""

import typer

from kanberoo_cli.commands import audit as audit_command
from kanberoo_cli.commands import backup as backup_command
from kanberoo_cli.commands import epic as epic_command
from kanberoo_cli.commands import export as export_command
from kanberoo_cli.commands import init as init_command
from kanberoo_cli.commands import server as server_command
from kanberoo_cli.commands import story as story_command
from kanberoo_cli.commands import tag as tag_command
from kanberoo_cli.commands import token as token_command
from kanberoo_cli.commands import workspace as workspace_command

app = typer.Typer(
    name="kanberoo",
    help="Kanberoo: a kanban-style issue tracker for terminals and AI agents.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _root() -> None:
    """
    Root callback. Exists only so Typer treats registered commands as
    subcommands; it has no side effects.
    """


app.command(
    name="init",
    help="Initialise the Kanberoo config directory, database, and first token.",
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
