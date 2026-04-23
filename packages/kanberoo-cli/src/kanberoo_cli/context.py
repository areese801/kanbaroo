"""
Per-command context helpers.

Most command handlers load the CLI config and spin up an
:class:`~kanberoo_cli.client.ApiClient` in the same pattern. Centralising
that pattern here keeps each command handler thin and makes it trivial
to test: injecting a custom :class:`httpx.MockTransport` only happens in
one place.
"""

from __future__ import annotations

from collections.abc import Callable

import typer
from rich.console import Console

from kanberoo_cli.client import ApiClient
from kanberoo_cli.config import (
    CliConfig,
    ConfigMalformedError,
    ConfigNotFoundError,
    load_config,
    load_config_api_only,
)

ClientFactory = Callable[[CliConfig], ApiClient]

_stderr_console = Console(stderr=True)


def require_config() -> CliConfig:
    """
    Load the CLI config or exit with a friendly error message.

    Keeps every command from re-implementing the same error-render
    plumbing.
    """
    try:
        return load_config()
    except ConfigNotFoundError as exc:
        _stderr_console.print(
            f"[red]Error:[/red] no Kanberoo config at {exc.path}.\n"
            "Run [bold]kb init[/bold] to create one."
        )
        raise typer.Exit(code=1) from exc
    except ConfigMalformedError as exc:
        _stderr_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


def require_config_api_only() -> CliConfig:
    """
    Like :func:`require_config` but does not demand ``database_url``.

    For commands that only hit the HTTP API (e.g.
    ``kb server start --wait``). The returned
    :class:`CliConfig.database_url` may be ``None``; the caller must
    not dereference it.
    """
    try:
        return load_config_api_only()
    except ConfigNotFoundError as exc:
        _stderr_console.print(
            f"[red]Error:[/red] no Kanberoo config at {exc.path}.\n"
            "Run [bold]kb init[/bold] to create one."
        )
        raise typer.Exit(code=1) from exc
    except ConfigMalformedError as exc:
        _stderr_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


def _default_client_factory(config: CliConfig) -> ApiClient:
    """
    Default implementation of :data:`_client_factory`: spin up a real
    HTTP-backed client against the user's configured API URL.
    """
    return ApiClient(base_url=config.api_url, token=config.token)


_client_factory: ClientFactory = _default_client_factory


def build_client(config: CliConfig) -> ApiClient:
    """
    Build an :class:`ApiClient` wired to the loaded config.

    Tests override this through :func:`set_client_factory` so they can
    hand back a client pre-bound to an :class:`httpx.MockTransport`.
    """
    return _client_factory(config)


def set_client_factory(factory: ClientFactory | None) -> None:
    """
    Override the client factory for the duration of a test.

    Passing ``None`` restores the default (real-HTTP) factory. The
    indirection is deliberate: patching the factory keeps the call
    sites in the command handlers identical to the production path.
    """
    global _client_factory
    _client_factory = factory or _default_client_factory
