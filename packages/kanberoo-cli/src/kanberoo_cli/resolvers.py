"""
ID-resolution helpers shared by commands.

Stories and epics are addressed in the CLI by their ``{KEY}-{N}`` human
identifiers (``KAN-123``); workspaces are addressed by their short key
(``KAN``) or by UUID. The REST API serves by-key lookups for every
entity directly so the CLI never has to walk the workspace list.

Most commands that accept ``--workspace`` also support a default: when
the flag is omitted, :func:`resolve_effective_workspace` falls back to
``$KANBEROO_WORKSPACE`` and then to ``default_workspace`` from
``config.toml`` before surfacing a friendly error.
"""

from __future__ import annotations

import os
from typing import Any

import typer

from kanberoo_cli.client import ApiClient, ApiRequestError
from kanberoo_cli.config import CliConfig
from kanberoo_cli.rendering import stderr_console


def _looks_like_human_id(candidate: str) -> bool:
    """
    Return True if ``candidate`` is shaped like ``{KEY}-{N}``.
    """
    if "-" not in candidate:
        return False
    head, tail = candidate.rsplit("-", 1)
    return bool(head) and tail.isdigit()


def resolve_workspace(client: ApiClient, key_or_id: str) -> dict[str, Any]:
    """
    Resolve a workspace by short key or UUID and return its full body.

    Workspace keys do not contain dashes (the conventional ``KAN``/
    ``DATA`` shape) whereas UUIDs do. Route any dashless reference
    straight to ``GET /workspaces/by-key/{key}``. Otherwise try the
    direct UUID endpoint first and fall back to the by-key endpoint for
    the rare hyphenated-key case. A 404 from the final lookup surfaces
    as :class:`ApiRequestError` with ``code="not_found"``.
    """
    if "-" not in key_or_id:
        response = client.get(f"/workspaces/by-key/{key_or_id}")
        body: dict[str, Any] = response.json()
        return body

    try:
        response = client.get(f"/workspaces/{key_or_id}")
    except ApiRequestError as exc:
        if exc.code != "not_found":
            raise
    else:
        direct: dict[str, Any] = response.json()
        return direct

    response = client.get(f"/workspaces/by-key/{key_or_id}")
    fallback: dict[str, Any] = response.json()
    return fallback


WORKSPACE_ENV_VAR = "KANBEROO_WORKSPACE"


class WorkspaceSource:
    """
    Labels for where an effective workspace came from.

    Consumed by ``kb workspace current`` to tell the user which source
    supplied the value.
    """

    FLAG = "flag"
    ENV = "env"
    CONFIG = "config"
    UNSET = "unset"


def effective_workspace(
    workspace_arg: str | None,
    config: CliConfig,
) -> tuple[str | None, str]:
    """
    Resolve the effective ``--workspace`` value and its source.

    Order, highest to lowest precedence:

    1. ``workspace_arg`` (the explicit ``--workspace`` flag),
    2. ``$KANBEROO_WORKSPACE`` environment variable,
    3. ``default_workspace`` in ``config.toml``.

    Returns ``(value, source)`` where ``value`` is ``None`` only when
    none of the three supplied a non-empty string. Callers that need a
    guaranteed value should use :func:`require_effective_workspace`.
    """
    if workspace_arg:
        return workspace_arg, WorkspaceSource.FLAG
    env_value = os.environ.get(WORKSPACE_ENV_VAR)
    if env_value:
        return env_value, WorkspaceSource.ENV
    if config.default_workspace:
        return config.default_workspace, WorkspaceSource.CONFIG
    return None, WorkspaceSource.UNSET


def require_effective_workspace(
    workspace_arg: str | None,
    config: CliConfig,
) -> str:
    """
    Resolve the effective workspace, exiting with a friendly Rich
    error when none of the three sources supplies one.

    Keeps every command handler's call site to a single line while
    still yielding the same ``exit 1`` / stderr-hint UX across the CLI.
    """
    value, _ = effective_workspace(workspace_arg, config)
    if value is None:
        stderr_console.print(
            "[red]Error:[/red] no workspace specified. "
            "Pass [bold]--workspace KEY[/bold], "
            f"set [bold]${WORKSPACE_ENV_VAR}[/bold], or run "
            "[bold]kb workspace use KEY[/bold]."
        )
        raise typer.Exit(code=1)
    return value


def resolve_story(client: ApiClient, ref: str) -> dict[str, Any]:
    """
    Resolve a story by ``{KEY}-{N}`` human id or by UUID.

    Uses ``GET /stories/by-key/{ref}`` when ``ref`` matches the
    human-id pattern, otherwise treats ``ref`` as a UUID and calls
    ``GET /stories/{ref}``.
    """
    if _looks_like_human_id(ref):
        response = client.get(f"/stories/by-key/{ref}")
    else:
        response = client.get(f"/stories/{ref}")
    body: dict[str, Any] = response.json()
    return body


def resolve_epic(client: ApiClient, ref: str) -> dict[str, Any]:
    """
    Resolve an epic by ``{KEY}-{N}`` human id or by UUID.

    Uses ``GET /epics/by-key/{ref}`` when ``ref`` matches the human-id
    pattern, otherwise treats ``ref`` as a UUID and calls
    ``GET /epics/{ref}``.
    """
    if _looks_like_human_id(ref):
        response = client.get(f"/epics/by-key/{ref}")
    else:
        response = client.get(f"/epics/{ref}")
    body: dict[str, Any] = response.json()
    return body


def try_resolve_other(
    client: ApiClient,
    ref: str,
    *,
    other: str,
) -> dict[str, Any] | None:
    """
    Attempt to resolve ``ref`` as the other entity kind and return it.

    ``other`` is either ``"story"`` or ``"epic"``. Used by ``kb story
    show`` and ``kb epic show`` to turn a 404 into a helpful "this
    looks like the other kind of entity" hint. Returns ``None`` when
    the other lookup also misses so callers fall back to the plain
    not-found message.
    """
    resolver = resolve_story if other == "story" else resolve_epic
    try:
        return resolver(client, ref)
    except ApiRequestError:
        return None
