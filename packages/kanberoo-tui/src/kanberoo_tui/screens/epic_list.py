"""
Epic list screen (spec section 8.1, "Epic list & detail").

Reached from the workspace list via ``E`` (capital, so it does not
clash with the ``e`` keybinding reserved by other screens for the
editor). Renders the workspace's epics as a :class:`DataTable` with
columns: human_id, title, state, story_count, updated_at. Story
counts walk the ``?epic_id=`` filter on the story list endpoint with
a bounded limit so the render budget stays small.

Pressing ``enter`` on a row posts :class:`EpicSelected`; the app
pushes the matching :class:`EpicDetailScreen`. The TUI follows cage
I's style (``story_detail`` / ``workspace_list``): DataTable-backed
rows, Vim keybindings, live refetch on WebSocket events, and a shared
help overlay via ``?``.
"""

from __future__ import annotations

import contextlib
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from kanberoo_tui.client import ApiError
from kanberoo_tui.messages import EpicSelected
from kanberoo_tui.widgets.help_modal import KeybindingHelp

EPIC_EVENT_PREFIX = "epic."
STORY_EVENT_PREFIX = "story."
STORY_COUNT_LIMIT = 200

HELP_ROWS: list[tuple[str, str]] = [
    ("j / k", "move cursor"),
    ("enter", "open epic detail"),
    ("r", "refresh list"),
    ("esc / q", "back"),
    ("?", "this overlay"),
]


class EpicListScreen(Screen[None]):
    """
    Lists epics in a single workspace.

    ``workspace`` is the raw REST body of the workspace that owns the
    epics; the screen reads ``id``, ``key``, and ``name`` off it and
    does not otherwise touch the workspace surface.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("enter", "open_selected", "Open", priority=True),
        Binding("r", "refresh_list", "Refresh"),
        Binding("q", "back", "Back"),
        Binding("escape", "back", "Back", show=False),
        Binding("?", "show_help", "Help", show=False),
    ]

    DEFAULT_CSS = """
    EpicListScreen {
        layout: vertical;
    }
    EpicListScreen > DataTable {
        height: 1fr;
    }
    """

    def __init__(self, workspace: dict[str, Any]) -> None:
        """
        Build an empty screen for ``workspace``. Rows fetch on
        :meth:`on_mount`.
        """
        super().__init__()
        self._workspace = workspace
        self._epics: list[dict[str, Any]] = []
        self._story_counts: dict[str, str] = {}

    @property
    def workspace(self) -> dict[str, Any]:
        """
        Return the workspace body (for tests).
        """
        return self._workspace

    @property
    def epics(self) -> list[dict[str, Any]]:
        """
        Return the current epics list (for tests).
        """
        return list(self._epics)

    def compose(self) -> ComposeResult:
        """
        Lay out the static chrome; rows populate after the first fetch.
        """
        yield Header()
        yield Vertical(id="epic-list-body")
        yield Footer()

    async def on_mount(self) -> None:
        """
        Register the WS listener, build the table, kick off the fetch.
        """
        self.sub_title = f"{self._workspace.get('key', '')} epics"
        body = self.query_one("#epic-list-body", Vertical)
        table: DataTable[str] = DataTable(
            id="epic-table", cursor_type="row", zebra_stripes=True
        )
        table.add_columns("key", "title", "state", "stories", "last updated")
        await body.mount(table)
        self.app.register_ws_listener(self)  # type: ignore[attr-defined]
        await self.refresh_data()
        table.focus()

    def on_unmount(self) -> None:
        """
        Deregister the WS listener so re-entering the screen registers
        fresh rather than leaking a stale reference.
        """
        self.app.unregister_ws_listener(self)  # type: ignore[attr-defined]

    async def refresh_data(self) -> None:
        """
        Re-fetch epics for the workspace and refill the table in place.
        """
        client = self.app.client  # type: ignore[attr-defined]
        workspace_id = str(self._workspace.get("id", ""))
        try:
            epics = await self._fetch_epics(client, workspace_id)
            counts = await self._fetch_story_counts(client, workspace_id, epics)
        except ApiError as exc:
            self.notify(f"epic fetch failed: {exc}", severity="error")
            return
        self._epics = epics
        self._story_counts = counts
        self._render_table()

    async def _fetch_epics(
        self,
        client: Any,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """
        Walk ``GET /workspaces/{id}/epics`` cursor-paginated until
        exhausted.
        """
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 200}
            if cursor is not None:
                params["cursor"] = cursor
            response = await client.get(
                f"/workspaces/{workspace_id}/epics",
                params=params,
            )
            body = response.json()
            items.extend(body.get("items", []))
            cursor = body.get("next_cursor")
            if cursor is None:
                break
        return items

    async def _fetch_story_counts(
        self,
        client: Any,
        workspace_id: str,
        epics: list[dict[str, Any]],
    ) -> dict[str, str]:
        """
        Return a map of epic-id to display string for the story count.

        Uses the ``?epic_id=`` filter with a bounded limit: callers that
        need the full story listing go through the board or a dedicated
        CLI command. ``200+`` marks an epic that outgrew the limit.
        """
        counts: dict[str, str] = {}
        for epic in epics:
            epic_id = str(epic.get("id", ""))
            response = await client.get(
                f"/workspaces/{workspace_id}/stories",
                params={"epic_id": epic_id, "limit": STORY_COUNT_LIMIT},
            )
            body = response.json()
            items = body.get("items", [])
            if body.get("next_cursor") is not None:
                counts[epic_id] = f"{len(items)}+"
            else:
                counts[epic_id] = str(len(items))
        return counts

    def _render_table(self) -> None:
        """
        Rebuild the table body from ``self._epics`` and
        ``self._story_counts``. Keeps the cursor on the selected row
        if it still exists after the refresh.
        """
        table = self.query_one("#epic-table", DataTable)
        previous_row_key = None
        if table.row_count:
            try:
                cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
                previous_row_key = cell_key.row_key.value
            except Exception:  # noqa: BLE001
                previous_row_key = None
        table.clear()
        for epic in self._epics:
            epic_id = str(epic.get("id", ""))
            table.add_row(
                str(epic.get("human_id", "")),
                str(epic.get("title", "")),
                str(epic.get("state", "")),
                self._story_counts.get(epic_id, "?"),
                str(epic.get("updated_at", "")),
                key=epic_id,
            )
        if previous_row_key is not None:
            with contextlib.suppress(Exception):
                table.move_cursor(row=table.get_row_index(previous_row_key))

    async def handle_ws_event(self, event: dict[str, Any]) -> None:
        """
        React to WebSocket events. Any ``epic.*`` or ``story.*`` event
        touching the current workspace triggers a refetch so story
        counts stay live.
        """
        event_type = str(event.get("event_type", ""))
        if not (
            event_type.startswith(EPIC_EVENT_PREFIX)
            or event_type.startswith(STORY_EVENT_PREFIX)
        ):
            return
        await self.refresh_data()

    def action_cursor_down(self) -> None:
        """
        Move the table cursor down.
        """
        self.query_one("#epic-table", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        """
        Move the table cursor up.
        """
        self.query_one("#epic-table", DataTable).action_cursor_up()

    async def action_refresh_list(self) -> None:
        """
        Keybinding handler for ``r``.
        """
        await self.refresh_data()
        self.notify("epics refreshed")

    def action_back(self) -> None:
        """
        Pop back to the caller (workspace list).
        """
        self.app.pop_screen()

    async def action_show_help(self) -> None:
        """
        Push the shared help overlay with this screen's bindings.
        """
        await self.app.push_screen(KeybindingHelp(title="Epics", bindings=HELP_ROWS))

    def action_open_selected(self) -> None:
        """
        Emit :class:`EpicSelected` for the row under the cursor.
        """
        if not self._epics:
            return
        table = self.query_one("#epic-table", DataTable)
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:  # noqa: BLE001
            return
        epic_id = cell_key.row_key.value
        if epic_id is None:
            return
        epic = next(
            (e for e in self._epics if str(e.get("id")) == epic_id),
            None,
        )
        if epic is None:
            return
        self.post_message(EpicSelected(self._workspace, epic))
