"""
Kanberoo CLI entry point.

Exposes the root Typer app with a no-op root callback so that Typer
always treats registered commands as subcommands (otherwise, a single
registered command gets flattened into a flag-less top-level command).
Later milestones register more commands onto the same ``app``.
"""

import typer

from kanberoo_cli.commands import init as init_command

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


if __name__ == "__main__":
    app()
