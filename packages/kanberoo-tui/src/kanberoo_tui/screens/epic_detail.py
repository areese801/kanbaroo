"""
Epic detail screen (spec section 8.1, "Epic list & detail").

Renders a single epic as a mini-board: five state columns scoped to
the epic's stories. Reuses :class:`BoardColumn` and :class:`StoryCard`
from the workspace board so the two views share layout, focus, and
theming. Pressing ``enter`` on a card pushes
:class:`StoryDetailScreen`; move mode (``m`` then ``b/t/p/r/d``)
issues the same transition request the full board does.

Live updates
------------

Subscribes to WebSocket events on mount and refetches on any
``epic.*`` event touching this epic or any ``story.*`` event whose
story belongs to it. Non-matching events are ignored so a chatty
unrelated workspace does not thrash this screen.
"""

from __future__ import annotations

from typing import Any, ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Header

from kanberoo_tui.client import ApiError
from kanberoo_tui.messages import StorySelected
from kanberoo_tui.screens.board import COLUMN_STATES, MOVE_KEY_TO_STATE
from kanberoo_tui.widgets.board_column import BoardColumn
from kanberoo_tui.widgets.help_modal import KeybindingHelp
from kanberoo_tui.widgets.story_card import StoryCard

EPIC_EVENT_PREFIX = "epic."
STORY_EVENT_PREFIX = "story."

HELP_ROWS: list[tuple[str, str]] = [
    ("h / l / \u2190 / \u2192", "move between columns"),
    ("j / k / \u2193 / \u2191", "move within a column"),
    ("enter", "open story detail"),
    ("m then b/t/p/r/d", "move the focused card"),
    ("r", "refresh"),
    ("esc / q", "back to epic list"),
    ("?", "this overlay"),
]


class EpicDetailScreen(Screen[None]):
    """
    Mini-board scoped to a single epic's stories.

    ``workspace`` and ``epic`` are the raw REST bodies. The screen
    only reads ``id`` off each; the workspace is retained so move mode
    posts to ``/stories/{id}/transition`` using the same path
    construction the board screen uses.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("h", "focus_prev_column", "Prev col", show=False),
        Binding("left", "focus_prev_column", "Prev col", show=False),
        Binding("l", "focus_next_column", "Next col", show=False),
        Binding("right", "focus_next_column", "Next col", show=False),
        Binding("j", "focus_next_card", "Next card", show=False),
        Binding("down", "focus_next_card", "Next card", show=False),
        Binding("k", "focus_prev_card", "Prev card", show=False),
        Binding("up", "focus_prev_card", "Prev card", show=False),
        Binding("m", "enter_move_mode", "Move"),
        Binding("enter", "open_detail", "Detail", priority=True),
        Binding("r", "refresh_screen", "Refresh"),
        Binding("?", "show_help", "Help", show=False),
        Binding("q", "back", "Back"),
        Binding("escape", "cancel_or_back", "Cancel/Back", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    EpicDetailScreen {
        layout: vertical;
    }
    EpicDetailScreen > Horizontal {
        height: 1fr;
    }
    """

    def __init__(self, workspace: dict[str, Any], epic: dict[str, Any]) -> None:
        """
        Build an empty mini-board for ``epic``. Cards load in
        :meth:`on_mount`.
        """
        super().__init__()
        self._workspace = workspace
        self._epic = epic
        self._stories: list[dict[str, Any]] = []
        self._move_mode: bool = False
        self._active_col: int = 0
        self._active_row: int = 0

    @property
    def workspace(self) -> dict[str, Any]:
        """
        Return the workspace body (for tests).
        """
        return self._workspace

    @property
    def epic(self) -> dict[str, Any]:
        """
        Return the epic body (for tests).
        """
        return self._epic

    @property
    def stories(self) -> list[dict[str, Any]]:
        """
        Return the current stories list (for tests).
        """
        return list(self._stories)

    @property
    def move_mode(self) -> bool:
        """
        Return ``True`` when move mode is active (for tests).
        """
        return self._move_mode

    def compose(self) -> ComposeResult:
        """
        Build the vertical chrome plus a five-column horizontal body.
        """
        yield Header()
        with Horizontal(id="epic-detail-columns"):
            for state_key, title in COLUMN_STATES:
                yield BoardColumn(
                    state_key=state_key,
                    title=title,
                    id=f"epic-col-{state_key}",
                )
        yield Footer()

    async def on_mount(self) -> None:
        """
        Register as the WS listener and load the scoped story list.
        """
        human_id = str(self._epic.get("human_id", ""))
        title = str(self._epic.get("title", ""))
        self.sub_title = f"{human_id} {title}"
        self.app.register_ws_listener(self)  # type: ignore[attr-defined]
        await self.refresh_data()

    def on_unmount(self) -> None:
        """
        Deregister the WS listener.
        """
        self.app.unregister_ws_listener(self)  # type: ignore[attr-defined]

    async def refresh_data(self) -> None:
        """
        Fetch stories for this epic and repopulate the columns.
        """
        client = self.app.client  # type: ignore[attr-defined]
        workspace_id = str(self._workspace.get("id", ""))
        epic_id = str(self._epic.get("id", ""))
        try:
            stories = await self._fetch_stories(client, workspace_id, epic_id)
        except ApiError as exc:
            self.notify(f"epic detail fetch failed: {exc}", severity="error")
            return
        self._stories = stories
        self._render_columns()
        self._restore_focus()

    async def _fetch_stories(
        self,
        client: Any,
        workspace_id: str,
        epic_id: str,
    ) -> list[dict[str, Any]]:
        """
        Walk ``GET /workspaces/{id}/stories?epic_id=<epic_id>`` until
        exhausted.
        """
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"epic_id": epic_id, "limit": 200}
            if cursor is not None:
                params["cursor"] = cursor
            response = await client.get(
                f"/workspaces/{workspace_id}/stories",
                params=params,
            )
            body = response.json()
            items.extend(body.get("items", []))
            cursor = body.get("next_cursor")
            if cursor is None:
                break
        return items

    def _render_columns(self) -> None:
        """
        Distribute stories into columns by state. Reuses
        :class:`StoryCard` so the look matches the main board.
        """
        by_state: dict[str, list[dict[str, Any]]] = {
            state: [] for state, _ in COLUMN_STATES
        }
        for story in self._stories:
            state = str(story.get("state", ""))
            if state in by_state:
                by_state[state].append(story)
        for state_key, _title in COLUMN_STATES:
            column = self.query_one(f"#epic-col-{state_key}", BoardColumn)
            cards = [StoryCard(story) for story in by_state[state_key]]
            column.set_cards(cards)

    def _restore_focus(self) -> None:
        """
        Re-focus the card at the active column/row after a refresh.
        """
        self._active_col = max(0, min(self._active_col, len(COLUMN_STATES) - 1))
        column = self._column_at(self._active_col)
        cards = column.cards
        if not cards:
            return
        self._active_row = max(0, min(self._active_row, len(cards) - 1))
        cards[self._active_row].focus()

    def _column_at(self, index: int) -> BoardColumn:
        """
        Return the :class:`BoardColumn` at ``index``.
        """
        state_key, _ = COLUMN_STATES[index]
        return self.query_one(f"#epic-col-{state_key}", BoardColumn)

    def _focused_card(self) -> StoryCard | None:
        """
        Return the currently focused card or ``None``.
        """
        column = self._column_at(self._active_col)
        cards = column.cards
        if not cards:
            return None
        self._active_row = max(0, min(self._active_row, len(cards) - 1))
        return cards[self._active_row]

    def action_focus_next_column(self) -> None:
        """
        Focus the next column's card at the same row (clamped).
        """
        if self._active_col + 1 >= len(COLUMN_STATES):
            return
        self._active_col += 1
        card = self._focused_card()
        if card is not None:
            card.focus()

    def action_focus_prev_column(self) -> None:
        """
        Focus the previous column's card at the same row (clamped).
        """
        if self._active_col - 1 < 0:
            return
        self._active_col -= 1
        card = self._focused_card()
        if card is not None:
            card.focus()

    def action_focus_next_card(self) -> None:
        """
        Focus the next card in the current column.
        """
        column = self._column_at(self._active_col)
        cards = column.cards
        if not cards:
            return
        self._active_row = min(self._active_row + 1, len(cards) - 1)
        cards[self._active_row].focus()

    def action_focus_prev_card(self) -> None:
        """
        Focus the previous card in the current column.
        """
        column = self._column_at(self._active_col)
        cards = column.cards
        if not cards:
            return
        self._active_row = max(self._active_row - 1, 0)
        cards[self._active_row].focus()

    def action_enter_move_mode(self) -> None:
        """
        Enter move mode so the next key picks a target state.
        """
        if self._focused_card() is None:
            self.notify("no card to move")
            return
        self._move_mode = True
        self.notify("move: b/t/p/r/d, esc to cancel")

    def action_cancel_or_back(self) -> None:
        """
        Cancel move mode when active; otherwise pop back to the caller.

        Mirrors the board's escape semantics: one key, two intents,
        disambiguated by whether move mode is engaged.
        """
        if self._move_mode:
            self._move_mode = False
            self.notify("move cancelled")
            return
        self.app.pop_screen()

    async def action_refresh_screen(self) -> None:
        """
        Keybinding handler for ``r``.
        """
        await self.refresh_data()
        self.notify("epic refreshed")

    def action_open_detail(self) -> None:
        """
        Post :class:`StorySelected` for the focused card so the app
        can push the detail screen.
        """
        card = self._focused_card()
        if card is None:
            self.notify("no card focused")
            return
        self.post_message(StorySelected(card.story))

    def action_back(self) -> None:
        """
        Pop back to the epic list.
        """
        self.app.pop_screen()

    async def action_show_help(self) -> None:
        """
        Push the shared help overlay with this screen's bindings.
        """
        await self.app.push_screen(
            KeybindingHelp(title="Epic detail", bindings=HELP_ROWS)
        )

    async def on_key(self, event: events.Key) -> None:
        """
        Consume the next key when move mode is active.
        """
        if not self._move_mode:
            return
        if event.key == "escape":
            return
        event.stop()
        target = MOVE_KEY_TO_STATE.get(event.key)
        self._move_mode = False
        if target is None:
            self.notify(f"unknown move target: {event.key}")
            return
        await self._transition_focused(target)

    async def _transition_focused(self, to_state: str) -> None:
        """
        POST the transition for the focused card.
        """
        card = self._focused_card()
        if card is None:
            self.notify("no card focused")
            return
        story = card.story
        story_id = str(story.get("id", ""))
        current_state = str(story.get("state", ""))
        if current_state == to_state:
            self.notify(f"already in {to_state}")
            return
        client = self.app.client  # type: ignore[attr-defined]
        try:
            await client.post_with_etag(
                f"/stories/{story_id}",
                f"/stories/{story_id}/transition",
                json={"to_state": to_state},
            )
        except ApiError as exc:
            self.notify(f"transition failed: {exc}", severity="error")
            return
        self.notify(f"moved {story.get('human_id')} -> {to_state}")
        await self.refresh_data()

    async def handle_ws_event(self, event: dict[str, Any]) -> None:
        """
        Refetch on epic or story events that touch this epic.

        ``epic.*`` events for this epic's id and any ``story.*`` event
        whose entity_id belongs to one of the current stories (or whose
        envelope carries an ``epic_id`` matching this epic) trigger a
        refresh. Anything else is ignored.
        """
        event_type = str(event.get("event_type", ""))
        entity_id = str(event.get("entity_id", ""))
        epic_id = str(self._epic.get("id", ""))
        if event_type.startswith(EPIC_EVENT_PREFIX):
            if entity_id == epic_id:
                await self.refresh_data()
            return
        if not event_type.startswith(STORY_EVENT_PREFIX):
            return
        story_ids = {str(s.get("id", "")) for s in self._stories}
        payload = event.get("payload") or {}
        payload_epic_id = (
            str(payload.get("epic_id", "")) if isinstance(payload, dict) else ""
        )
        if entity_id in story_ids or payload_epic_id == epic_id:
            await self.refresh_data()
