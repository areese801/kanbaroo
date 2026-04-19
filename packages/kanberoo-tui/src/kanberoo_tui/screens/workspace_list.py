"""
Workspace list screen (milestone 11 landing view).

Fetches ``GET /workspaces`` on mount and renders each row with a
story count, an epic count, and the server-reported ``updated_at``
timestamp. Story and epic counts come from one extra request per
workspace, which keeps the render budget bounded for the single-user
scale phase 1 targets; a future milestone can switch to a
``?count_only=1`` server flag if the budget ever becomes a real
concern.

WebSocket hookup
----------------

The screen registers itself as the current WS listener with the app
on mount and deregisters on unmount. Any ``workspace.*`` event
triggers a full refetch; optimistic single-row updates are deferred
to keep the first cut simple.

Quit handling
-------------

``q`` pushes the :class:`QuitConfirmModal` so a stray keypress never
exits the app; a second ``q`` within :data:`FAST_QUIT_WINDOW_SECONDS`
skips the modal and quits directly so power users who know what they
mean can still double-tap out.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Header, Static

from kanberoo_tui.client import ApiError
from kanberoo_tui.messages import (
    OpenAuditFeed,
    OpenEpicList,
    OpenSearch,
    WorkspaceSelected,
)
from kanberoo_tui.widgets.help_modal import KeybindingHelp

WORKSPACE_EVENT_PREFIX = "workspace."

FAST_QUIT_WINDOW_SECONDS = 0.8

HELP_ROWS: list[tuple[str, str]] = [
    ("j / k", "move cursor"),
    ("enter / l / right", "open workspace board"),
    ("E", "open epic list"),
    ("/", "fuzzy search"),
    ("a", "global audit feed"),
    ("r", "refresh list"),
    ("q", "quit (confirm; double-tap for fast exit)"),
    ("?", "this overlay"),
]


class QuitConfirmModal(ModalScreen[bool]):
    """
    Small confirmation modal for ``q`` on the workspace list.

    Dismisses with ``True`` to quit and ``False`` to return to the
    caller. Dedicated modal (rather than a stock prompt) keeps the
    dialog tiny and keyboard-first: ``y``/``enter`` accept, ``n``/
    ``escape`` dismiss, anything else is ignored so a stray keypress
    in the confirm path never quits the app.

    Fast-exit: a ``q`` press while the modal has been visible less
    than :data:`FAST_QUIT_WINDOW_SECONDS` is treated as the second
    half of a power-user double-tap and calls ``app.exit()`` directly
    (otherwise it cancels like ``n``/``escape``). The gate lives on
    the modal because the screen's ``q`` binding is shadowed the
    moment the modal mounts, so a screen-only timer never sees the
    follow-up press.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "confirm", "Yes", priority=True),
        Binding("enter", "confirm", "Yes", priority=True),
        Binding("n", "cancel", "No", priority=True),
        Binding("escape", "cancel", "No", priority=True),
        Binding("q", "q_fast_exit_or_cancel", "No", priority=True),
    ]

    DEFAULT_CSS = """
    QuitConfirmModal {
        align: center middle;
    }
    QuitConfirmModal > Vertical {
        width: 30;
        height: auto;
        border: round $accent;
        background: $panel;
        padding: 1 2;
    }
    QuitConfirmModal .confirm-title {
        text-style: bold;
        color: $accent;
    }
    QuitConfirmModal .confirm-hint {
        color: $text-muted;
        padding-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        """
        Lay out the centered confirm box.

        The hint escapes its square brackets for Rich markup (``\\[``)
        so ``[Y]es / [N]o`` renders literally instead of Rich swallowing
        ``[y]`` and ``[n]`` as unknown tags and leaving ``es / o`` on
        screen (cage delta regression).
        """
        with Vertical():
            yield Static("Quit Kanberoo?", classes="confirm-title")
            yield Static(
                "\\[Y]es  /  \\[N]o",
                classes="confirm-hint",
                id="quit-confirm-hint",
            )

    def __init__(self) -> None:
        """
        Build the modal. ``_opened_at`` fills in :meth:`on_mount` so
        the fast-exit window is measured against the moment the modal
        actually becomes visible.
        """
        super().__init__()
        self._opened_at: float = 0.0

    def on_mount(self) -> None:
        """
        Record the mount timestamp so ``action_q_fast_exit_or_cancel``
        can tell a rapid double-tap apart from a considered cancel.
        """
        self._opened_at = time.monotonic()

    def action_confirm(self) -> None:
        """
        Dismiss with ``True`` so the caller quits.
        """
        self.dismiss(True)

    def action_cancel(self) -> None:
        """
        Dismiss with ``False`` so the caller stays on the list.
        """
        self.dismiss(False)

    def action_q_fast_exit_or_cancel(self) -> None:
        """
        Handle ``q`` while the modal is open.

        A ``q`` landing within :data:`FAST_QUIT_WINDOW_SECONDS` of the
        modal opening is treated as the second press in a double-tap
        quit and exits the app immediately; otherwise it cancels the
        modal like ``n``/``escape``.
        """
        if time.monotonic() - self._opened_at <= FAST_QUIT_WINDOW_SECONDS:
            self.app.exit()
            return
        self.dismiss(False)


class WorkspaceListScreen(Screen[None]):
    """
    Landing screen: lists workspaces in a :class:`DataTable`.

    The table drives focus. Screen-level bindings translate Vim-style
    keys (``j``/``k``/``l``) into the matching DataTable actions so the
    whole screen responds to Vim keys without subclassing DataTable.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False, priority=True),
        Binding("k", "cursor_up", "Up", show=False, priority=True),
        Binding("l", "open_selected", "Open", show=False),
        Binding("right", "open_selected", "Open", show=False),
        Binding("enter", "open_selected", "Open", priority=True),
        Binding("slash", "open_search", "Search", show=False),
        Binding("a", "open_audit_feed", "Audit"),
        Binding("E", "open_epic_list", "Epics", show=False),
        Binding("r", "refresh_list", "Refresh"),
        Binding("?", "show_help", "Help", show=False),
        Binding("q", "quit_with_confirm", "Quit", priority=True),
    ]

    DEFAULT_CSS = """
    WorkspaceListScreen {
        layout: vertical;
    }
    WorkspaceListScreen > .ws-empty {
        padding: 2 4;
        color: $warning;
    }
    WorkspaceListScreen > DataTable {
        height: 1fr;
    }
    """

    def __init__(self) -> None:
        """
        Build an empty screen; data is fetched on :meth:`on_mount`.
        """
        super().__init__()
        self._workspaces: list[dict[str, Any]] = []
        self._counts: dict[str, tuple[str, str]] = {}
        self._last_q_at: float = 0.0

    def compose(self) -> ComposeResult:
        """
        Lay out the static chrome. Rows are populated after the first
        REST round-trip completes in :meth:`on_mount`.
        """
        yield Header()
        yield Vertical(id="ws-body")
        yield Footer()

    async def on_mount(self) -> None:
        """
        Register as the current WS listener, build the table, and kick
        off the initial fetch.
        """
        self.sub_title = "Workspaces"
        body = self.query_one("#ws-body", Vertical)
        table: DataTable[str] = DataTable(
            id="ws-table", cursor_type="row", zebra_stripes=True
        )
        table.add_columns("key", "name", "stories", "epics", "last updated")
        await body.mount(table)
        self.app.register_ws_listener(self)  # type: ignore[attr-defined]
        await self.refresh_data()
        table.focus()

    def on_unmount(self) -> None:
        """
        Deregister as the WS listener so a later push of the same
        screen can re-register cleanly.
        """
        self.app.unregister_ws_listener(self)  # type: ignore[attr-defined]

    async def refresh_data(self) -> None:
        """
        Re-fetch workspaces and refill the table in place.
        """
        client = self.app.client  # type: ignore[attr-defined]
        try:
            workspaces = await self._fetch_workspaces(client)
            counts = await self._fetch_counts(client, workspaces)
        except ApiError as exc:
            self.notify(f"workspace fetch failed: {exc}", severity="error")
            return
        self._workspaces = workspaces
        self._counts = counts
        self._render_table()

    async def _fetch_workspaces(self, client: Any) -> list[dict[str, Any]]:
        """
        Walk ``GET /workspaces`` cursor-paginated until exhausted.
        """
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 200}
            if cursor is not None:
                params["cursor"] = cursor
            response = await client.get("/workspaces", params=params)
            body = response.json()
            items.extend(body.get("items", []))
            cursor = body.get("next_cursor")
            if cursor is None:
                break
        return items

    async def _fetch_counts(
        self,
        client: Any,
        workspaces: list[dict[str, Any]],
    ) -> dict[str, tuple[str, str]]:
        """
        Fetch story and epic counts for each workspace.

        One request per endpoint per workspace with ``limit=200``;
        local ``len`` with a ``200+`` sentinel when the server reports
        another page. Small N by design, so the blast radius is
        capped by the number of workspaces.
        """
        counts: dict[str, tuple[str, str]] = {}
        for workspace in workspaces:
            ws_id = str(workspace.get("id", ""))
            stories = await self._count(client, f"/workspaces/{ws_id}/stories")
            epics = await self._count(client, f"/workspaces/{ws_id}/epics")
            counts[ws_id] = (stories, epics)
        return counts

    async def _count(self, client: Any, path: str) -> str:
        """
        Return a display string for a paginated endpoint's count.

        Never raises for API errors: a failed count renders as ``?``
        so the rest of the row still shows. Transport-level errors
        propagate so the caller can surface a notification once.
        """
        response = await client.get(path, params={"limit": 200})
        body = response.json()
        items = body.get("items", [])
        if body.get("next_cursor") is not None:
            return f"{len(items)}+"
        return str(len(items))

    def _render_table(self) -> None:
        """
        Rebuild the table body from ``self._workspaces`` and
        ``self._counts``. Keeps the current cursor position if the
        selected row still exists.
        """
        table = self.query_one("#ws-table", DataTable)
        previous_row_key = None
        if table.row_count:
            try:
                cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
                previous_row_key = cell_key.row_key.value
            except Exception:  # noqa: BLE001
                previous_row_key = None
        table.clear()
        if not self._workspaces:
            return
        for workspace in self._workspaces:
            ws_id = str(workspace.get("id", ""))
            stories, epics = self._counts.get(ws_id, ("?", "?"))
            table.add_row(
                str(workspace.get("key", "")),
                str(workspace.get("name", "")),
                stories,
                epics,
                str(workspace.get("updated_at", "")),
                key=ws_id,
            )
        if previous_row_key is not None:
            with contextlib.suppress(Exception):
                table.move_cursor(row=table.get_row_index(previous_row_key))

    async def handle_ws_event(self, event: dict[str, Any]) -> None:
        """
        React to a WebSocket event. Any ``workspace.*`` event triggers
        a refetch; non-workspace events are ignored at this level so
        the board screen can own story/epic live updates.
        """
        event_type = str(event.get("event_type", ""))
        if event_type.startswith(WORKSPACE_EVENT_PREFIX):
            await self.refresh_data()

    def action_cursor_down(self) -> None:
        """
        Move the table cursor down.
        """
        table = self.query_one("#ws-table", DataTable)
        table.action_cursor_down()

    def action_cursor_up(self) -> None:
        """
        Move the table cursor up.
        """
        table = self.query_one("#ws-table", DataTable)
        table.action_cursor_up()

    async def action_refresh_list(self) -> None:
        """
        Keybinding handler for ``r``.
        """
        await self.refresh_data()
        self.notify("workspaces refreshed")

    def action_open_search(self) -> None:
        """
        Ask the app to push the fuzzy-search overlay.
        """
        self.post_message(OpenSearch())

    def action_open_audit_feed(self) -> None:
        """
        Ask the app to push the global audit feed.
        """
        self.post_message(OpenAuditFeed())

    def action_open_epic_list(self) -> None:
        """
        Ask the app to push the epic list for the highlighted row.

        Does nothing when there are no rows yet: pressing ``E`` on an
        empty list is a no-op rather than an error.
        """
        if not self._workspaces:
            return
        table = self.query_one("#ws-table", DataTable)
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:  # noqa: BLE001
            return
        ws_id = cell_key.row_key.value
        if ws_id is None:
            return
        workspace = next(
            (ws for ws in self._workspaces if str(ws.get("id")) == ws_id),
            None,
        )
        if workspace is None:
            return
        self.post_message(OpenEpicList(workspace))

    async def action_show_help(self) -> None:
        """
        Push the shared help overlay with this screen's bindings.
        """
        await self.app.push_screen(
            KeybindingHelp(title="Workspaces", bindings=HELP_ROWS)
        )

    async def action_quit_with_confirm(self) -> None:
        """
        Ask before quitting, with a rapid-double-tap fast-exit.

        A single ``q`` pushes :class:`QuitConfirmModal`. The modal
        owns the double-tap window for the common case (second ``q``
        is consumed by the modal); the screen-level timer here catches
        the rare case where the modal dismisses between presses and a
        second ``q`` arrives back on the screen within the window. The
        dismiss callback resets ``_last_q_at`` so a deliberate later
        ``q`` still opens a fresh modal instead of snapping straight
        into fast-exit mode.
        """
        now = time.monotonic()
        if now - self._last_q_at <= FAST_QUIT_WINDOW_SECONDS:
            self._last_q_at = 0.0
            self.app.exit()
            return
        self._last_q_at = now

        def _on_dismiss(result: bool | None) -> None:
            if result:
                self.app.exit()
                return
            self._last_q_at = 0.0

        await self.app.push_screen(QuitConfirmModal(), _on_dismiss)

    def action_open_selected(self) -> None:
        """
        Emit :class:`WorkspaceSelected` for the row under the cursor.

        Does nothing when there are no rows yet: pressing ``enter`` on
        an empty table is a no-op rather than an error.
        """
        if not self._workspaces:
            return
        table = self.query_one("#ws-table", DataTable)
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:  # noqa: BLE001
            return
        ws_id = cell_key.row_key.value
        if ws_id is None:
            return
        workspace = next(
            (ws for ws in self._workspaces if str(ws.get("id")) == ws_id),
            None,
        )
        if workspace is None:
            return
        self.post_message(WorkspaceSelected(workspace))

    def empty_state(self) -> Static | None:
        """
        Return the empty-state widget if present; returns ``None``
        otherwise. Exposed so tests can assert on the empty branch
        without reaching into private state.
        """
        matches = self.query(".ws-empty")
        if not matches:
            return None
        first = matches.first()
        return first if isinstance(first, Static) else None

    @property
    def workspaces(self) -> list[dict[str, Any]]:
        """
        Return a copy of the current workspaces list; useful for
        assertions and the board screen.
        """
        return list(self._workspaces)
