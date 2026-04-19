"""
Global audit feed screen (milestone 14).

Reached from the workspace list via ``a``. Renders the tail of the
global audit log as a table and appends any events the WebSocket
stream delivers so the feed stays live without polling.

Endpoint tolerance
------------------

``GET /api/v1/audit`` is cage K's work. This screen wires the call
and renders a friendly "audit endpoint not yet available" line on a
404. Live WS events still populate the table once they start
arriving, so the screen is useful even before the REST endpoint
lands. A 200 from a newer server replaces the placeholder with the
real seed rows.

Keybindings
-----------

* ``r``: re-fetch from ``/audit`` (reconciles anything missed while
  the screen was backgrounded).
* ``escape`` / ``q``: back to the caller.
* ``?``: shared help overlay.
"""

from __future__ import annotations

from collections import deque
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from kanberoo_tui.client import ApiError, ApiRequestError
from kanberoo_tui.widgets.help_modal import KeybindingHelp
from kanberoo_tui.widgets.story_card import actor_badge

MAX_ROWS = 500
FETCH_LIMIT = 50

STATE_CHANGED_ACTION = "state_changed"


def format_state_transition(event: dict[str, Any]) -> str | None:
    """
    Return a ``<from> -> <to>`` string for a ``state_changed`` audit row.

    Reads ``before.state`` and ``after.state`` out of the already-parsed
    ``diff`` dict (see ``AuditEventRead`` in ``kanberoo-core``). Appends
    ``(<reason>)`` when ``after.transition_reason`` is set. Returns
    ``None`` for any event whose action is not ``state_changed`` or
    whose diff does not carry the expected shape; callers fall back to
    their default rendering in that case.
    """
    action = str(event.get("action", ""))
    if action != STATE_CHANGED_ACTION:
        return None
    diff = event.get("diff")
    if not isinstance(diff, dict):
        return None
    before = diff.get("before") if isinstance(diff.get("before"), dict) else {}
    after = diff.get("after") if isinstance(diff.get("after"), dict) else {}
    from_state = str(before.get("state", "?")) if before else "?"
    to_state = str(after.get("state", "?")) if after else "?"
    rendered = f"{from_state} \u2192 {to_state}"
    reason = after.get("transition_reason") if isinstance(after, dict) else None
    if reason:
        rendered = f"{rendered} ({reason})"
    return rendered


HELP_ROWS: list[tuple[str, str]] = [
    ("r", "refresh from /audit"),
    ("q / esc", "back"),
    ("?", "this overlay"),
]


class AuditFeedScreen(Screen[None]):
    """
    Live tail of the global audit feed.

    Stores events in a :class:`collections.deque` capped at
    :data:`MAX_ROWS` so a long session does not eat memory; rows
    above the cap are evicted in insertion order (oldest rendered
    row drops off first since we prepend on WS delivery).
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("r", "reconcile", "Refresh"),
        Binding("q", "back", "Back"),
        Binding("escape", "back", "Back", show=False),
        Binding("?", "show_help", "Help", show=False),
    ]

    DEFAULT_CSS = """
    AuditFeedScreen {
        layout: vertical;
    }
    AuditFeedScreen DataTable {
        height: 1fr;
    }
    AuditFeedScreen .audit-empty {
        padding: 1 2;
        color: $warning;
    }
    """

    def __init__(self) -> None:
        """
        Build an empty audit feed; data loads on :meth:`on_mount`.
        """
        super().__init__()
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_ROWS)
        self._unavailable: bool = False

    def compose(self) -> ComposeResult:
        """
        Lay out the static chrome; the body fills after the fetch.
        """
        yield Header()
        yield Vertical(id="audit-body")
        yield Footer()

    async def on_mount(self) -> None:
        """
        Build the table, register for WS events, fetch the first page.
        """
        self.sub_title = "Audit"
        body = self.query_one("#audit-body", Vertical)
        table: DataTable[str] = DataTable(
            id="audit-table", cursor_type="row", zebra_stripes=True
        )
        table.add_columns("when", "actor", "action", "entity", "id")
        await body.mount(table)
        self.app.register_ws_listener(self)  # type: ignore[attr-defined]
        await self._reconcile()

    def on_unmount(self) -> None:
        """
        Deregister the WS listener.
        """
        self.app.unregister_ws_listener(self)  # type: ignore[attr-defined]

    async def _reconcile(self) -> None:
        """
        Re-fetch from ``/audit``; tolerate 404 while cage K is pending.
        """
        client = self.app.client  # type: ignore[attr-defined]
        try:
            response = await client.get("/audit", params={"limit": FETCH_LIMIT})
        except ApiRequestError as exc:
            if exc.status_code == 404:
                self._unavailable = True
                self._render_empty()
                return
            self.notify(f"audit fetch failed: {exc}", severity="error")
            return
        except ApiError as exc:
            self.notify(f"audit fetch failed: {exc}", severity="error")
            return
        body = response.json()
        if isinstance(body, dict):
            items = list(body.get("items", []))
        elif isinstance(body, list):
            items = list(body)
        else:
            items = []
        self._unavailable = False
        self._events.clear()
        # Newest-first: the endpoint already returns reverse chron; we
        # preserve order in the deque so subsequent WS prepends stay
        # consistent.
        for event in items:
            self._events.append(event)
        self._render_all()

    def _render_empty(self) -> None:
        """
        Show the "endpoint not yet available" placeholder.
        """
        body = self.query_one("#audit-body", Vertical)
        table = self.query_one("#audit-table", DataTable)
        table.clear()
        matches = body.query(".audit-empty")
        if matches:
            return
        body.mount(
            Static(
                "audit endpoint not yet available (cage K). "
                "Live events will still appear here.",
                classes="audit-empty",
            ),
            after=table,
        )

    def _render_all(self) -> None:
        """
        Rebuild the table from ``self._events``.
        """
        table = self.query_one("#audit-table", DataTable)
        table.clear()
        for event in self._events:
            table.add_row(*_event_row(event))
        body = self.query_one("#audit-body", Vertical)
        for placeholder in list(body.query(".audit-empty")):
            placeholder.remove()

    def _prepend_event(self, event: dict[str, Any]) -> None:
        """
        Add one event to the top of the table and trim the deque.

        DataTable has no prepend helper, so we clear and rebuild from
        the deque. The cap at :data:`MAX_ROWS` keeps rebuild costs
        bounded and avoids index-bookkeeping bugs that a manual insert
        would introduce.
        """
        self._events.appendleft(event)
        self._render_all()

    async def action_reconcile(self) -> None:
        """
        Keybinding handler for ``r`` (labelled "Refresh" in the
        binding list for consistency with every other screen). The
        internal method name stays as "reconcile" because the action
        also reconciles events missed while the screen was
        backgrounded.
        """
        await self._reconcile()
        self.notify("audit refreshed")

    def action_back(self) -> None:
        """
        Pop back to the caller.
        """
        self.app.pop_screen()

    async def action_show_help(self) -> None:
        """
        Push the shared help overlay.
        """
        await self.app.push_screen(
            KeybindingHelp(title="Audit feed", bindings=HELP_ROWS)
        )

    async def handle_ws_event(self, event: dict[str, Any]) -> None:
        """
        Treat every WS event as an audit entry and prepend it.

        Skip pings (they are filtered upstream in :mod:`kanberoo_tui.ws`
        but the guard is cheap) and envelopes missing an ``event_type``.
        """
        if "event_type" not in event:
            return
        # Remove the placeholder the first time a live event arrives.
        if self._unavailable:
            self._unavailable = False
        self._prepend_event(event)

    @property
    def events(self) -> list[dict[str, Any]]:
        """
        Return a copy of the events deque (for tests).
        """
        return list(self._events)


def _event_row(event: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """
    Convert an event envelope into the five display cells.

    For ``state_changed`` rows the ``action`` cell is augmented with the
    ``from -> to`` transition so the audit feed makes the move obvious
    at a glance without forcing the reader to drill into the raw diff.
    """
    when = str(event.get("occurred_at", ""))
    actor_type = str(event.get("actor_type", "?"))
    actor_id = str(event.get("actor_id", "?"))
    actor = f"{actor_badge(actor_type)} {actor_id}"
    action = str(event.get("event_type", event.get("action", "")))
    transition = format_state_transition(event)
    if transition is not None:
        action = f"{action}  {transition}"
    entity = str(event.get("entity_type", ""))
    entity_id = str(event.get("entity_id", ""))
    short_id = entity_id[:8] if entity_id else ""
    return when, actor, action, entity, short_id
