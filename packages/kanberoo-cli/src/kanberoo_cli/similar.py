"""
Shared helpers for the duplicate-title check used by ``kb story``,
``kb epic``, and ``kb tag`` ``create`` commands.

The wired flow is the same for every entity type: query the
``similar`` endpoint with the proposed title (or name), and either
prompt the user to abort, skip the prompt under ``--force``, or fold
the matches into a ``warnings`` field for ``--json`` output. The
shape of the entity differs (stories and epics carry ``human_id``;
tags carry ``name``), so callers pick the label key they want
displayed.
"""

from __future__ import annotations

from typing import Any

from kanberoo_cli.client import ApiClient
from kanberoo_cli.rendering import stdout_console


def fetch_similar_entities(
    client: ApiClient,
    *,
    workspace_id: str,
    resource: str,
    field_name: str,
    value: str,
) -> list[dict[str, Any]]:
    """
    Call ``GET /workspaces/{id}/{resource}/similar?{field_name}=...``
    and return the ``items`` list.

    ``resource`` is the URL segment (``stories``, ``epics``,
    ``tags``); ``field_name`` is the query-string key the endpoint
    expects (``title`` for stories and epics, ``name`` for tags).
    """
    response = client.get(
        f"/workspaces/{workspace_id}/{resource}/similar",
        params={field_name: value},
    )
    body: dict[str, Any] = response.json()
    items = body.get("items") or []
    return [item for item in items if isinstance(item, dict)]


def print_similar_entities(
    items: list[dict[str, Any]],
    *,
    label_key: str,
    entity: str,
) -> None:
    """
    Render a short list of similar entities to stdout for the
    interactive prompt.

    ``label_key`` is the field rendered in the second column
    (``human_id`` for stories and epics, ``name`` for tags). The
    table is intentionally small; we want the user to see the
    overlap, not browse a result set.
    """
    plural = entity if items and len(items) == 1 else f"{entity}s"
    stdout_console.print(f"[yellow]Found {len(items)} similar {plural}:[/yellow]")
    for item in items:
        label = str(item.get(label_key, "?"))
        title = str(item.get("title") or item.get("name") or "")
        stdout_console.print(f"  - {label}  {title}")
