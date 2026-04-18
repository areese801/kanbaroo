"""
Board view (milestone 12) for a single workspace.

Five columns laid out horizontally map to the states defined in the
spec section 4.3 state machine: ``backlog``, ``todo``, ``in_progress``,
``in_review``, ``done``. Each column holds zero or more
:class:`~kanberoo_tui.widgets.story_card.StoryCard` widgets.

Keyboard navigation is explicit: the screen owns two integers
(``_active_col``, ``_active_row``) and moves focus to the right card
on ``h``/``l``/``j``/``k``. Move mode (``m``) captures the next key
and translates ``b`` / ``t`` / ``p`` / ``r`` / ``d`` into a
``POST /stories/{id}/transition`` with the card's current ETag as
``If-Match``. On success the board refetches; the card shows up in
its new column after the refresh.

Cage I adds three new surfaces:

* ``enter`` on a card pushes :class:`StoryDetailScreen` instead of
  flashing a placeholder.
* ``n`` opens ``$EDITOR`` on a story template; saving creates a
  new story in the current workspace.
* ``/`` opens the global fuzzy-search overlay via the
  :class:`OpenSearch` message.
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
from kanberoo_tui.editor import EditorRunner, edit_markdown
from kanberoo_tui.messages import OpenSearch, StorySelected
from kanberoo_tui.widgets.board_column import BoardColumn
from kanberoo_tui.widgets.help_modal import KeybindingHelp
from kanberoo_tui.widgets.story_card import StoryCard

COLUMN_STATES: list[tuple[str, str]] = [
    ("backlog", "Backlog"),
    ("todo", "Todo"),
    ("in_progress", "In Progress"),
    ("in_review", "In Review"),
    ("done", "Done"),
]

MOVE_KEY_TO_STATE: dict[str, str] = {
    "b": "backlog",
    "t": "todo",
    "p": "in_progress",
    "r": "in_review",
    "d": "done",
}

STORY_EVENT_PREFIX = "story."

NEW_STORY_TEMPLATE = "# Title (replace this line)\n\n# Description below\n\n"

PLACEHOLDER_TITLE = "Title (replace this line)"

HELP_ROWS: list[tuple[str, str]] = [
    ("h / l / \u2190 / \u2192", "move between columns"),
    ("j / k / \u2193 / \u2191", "move within a column"),
    ("enter", "open story detail"),
    ("m then b/t/p/r/d", "move the focused card"),
    ("n", "new story via $EDITOR"),
    ("/", "fuzzy search"),
    ("r", "refresh board"),
    ("q", "back to workspace list"),
    ("?", "this overlay"),
]


class BoardScreen(Screen[None]):
    """
    Kanban board for one workspace.

    ``workspace`` is the REST body of the selected workspace; the
    screen reads ``id``, ``key``, and ``name`` off it and does not
    otherwise touch the workspace surface.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("h", "focus_prev_column", "Prev col", show=False, priority=True),
        Binding("left", "focus_prev_column", "Prev col", show=False, priority=True),
        Binding("l", "focus_next_column", "Next col", show=False, priority=True),
        Binding("right", "focus_next_column", "Next col", show=False, priority=True),
        Binding("j", "focus_next_card", "Next card", show=False, priority=True),
        Binding("down", "focus_next_card", "Next card", show=False, priority=True),
        Binding("k", "focus_prev_card", "Prev card", show=False, priority=True),
        Binding("up", "focus_prev_card", "Prev card", show=False, priority=True),
        Binding("m", "enter_move_mode", "Move"),
        Binding("enter", "open_detail", "Detail"),
        Binding("n", "new_story", "New"),
        Binding("slash", "open_search", "Search", show=False),
        Binding("r", "refresh_board", "Refresh"),
        Binding("?", "show_help", "Help", show=False),
        Binding("q", "back", "Back", priority=True),
        Binding("escape", "cancel_move_mode", "Cancel move", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    BoardScreen {
        layout: vertical;
    }
    BoardScreen > Horizontal {
        height: 1fr;
    }
    """

    def __init__(
        self,
        workspace: dict[str, Any],
        *,
        editor_runner: EditorRunner | None = None,
    ) -> None:
        """
        Build an empty board for ``workspace``. Cards load in
        :meth:`on_mount`. ``editor_runner`` forwards to
        :func:`edit_markdown` for ``n``; tests inject a fake so the
        new-story template fills itself without launching a real
        editor.
        """
        super().__init__()
        self._workspace = workspace
        self._stories: list[dict[str, Any]] = []
        self._tags_by_story: dict[str, list[dict[str, Any]]] = {}
        self._move_mode: bool = False
        self._active_col: int = 0
        self._active_row: int = 0
        self._editor_runner = editor_runner

    def compose(self) -> ComposeResult:
        """
        Build the vertical chrome plus the five-column horizontal body.
        """
        yield Header()
        with Horizontal(id="board-columns"):
            for state_key, title in COLUMN_STATES:
                yield BoardColumn(
                    state_key=state_key,
                    title=title,
                    id=f"col-{state_key}",
                )
        yield Footer()

    @property
    def workspace(self) -> dict[str, Any]:
        """
        Return the workspace body so tests can assert the screen was
        constructed correctly.
        """
        return self._workspace

    @property
    def current_workspace(self) -> dict[str, Any]:
        """
        Return the workspace this screen is scoped to.

        Exposed for the app's global ``E`` binding, which walks the
        screen stack looking for the effective workspace without
        touching internal state.
        """
        return self._workspace

    @property
    def stories(self) -> list[dict[str, Any]]:
        """
        Return the current stories list.
        """
        return list(self._stories)

    @property
    def move_mode(self) -> bool:
        """
        Return ``True`` when move-mode is active; exposed for tests.
        """
        return self._move_mode

    async def on_mount(self) -> None:
        """
        Register as the WS listener and load the board data.
        """
        key = str(self._workspace.get("key", ""))
        self.sub_title = f"{key} - Board" if key else "Board"
        self.app.register_ws_listener(self)  # type: ignore[attr-defined]
        await self.refresh_data()

    def on_unmount(self) -> None:
        """
        Deregister the WS listener so re-entering the screen from the
        workspace list registers fresh.
        """
        self.app.unregister_ws_listener(self)  # type: ignore[attr-defined]

    async def refresh_data(self) -> None:
        """
        Fetch all stories for the workspace and repopulate columns.

        Walks the paginated story endpoint with ``limit=200`` so a
        workspace with a few hundred stories renders in one round-trip
        pair.
        """
        client = self.app.client  # type: ignore[attr-defined]
        workspace_id = str(self._workspace.get("id", ""))
        try:
            stories = await self._fetch_stories(client, workspace_id)
        except ApiError as exc:
            self.notify(f"board fetch failed: {exc}", severity="error")
            return
        self._stories = stories
        self._render_columns()
        self._restore_focus()

    async def _fetch_stories(
        self,
        client: Any,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """
        Walk ``GET /workspaces/{id}/stories`` until exhausted.
        """
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 200}
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
        Distribute stories into columns by state.
        """
        by_state: dict[str, list[dict[str, Any]]] = {
            state: [] for state, _ in COLUMN_STATES
        }
        for story in self._stories:
            state = str(story.get("state", ""))
            if state in by_state:
                by_state[state].append(story)
        for state_key, _title in COLUMN_STATES:
            column = self.query_one(f"#col-{state_key}", BoardColumn)
            tags_lookup = self._tags_by_story
            cards = [
                StoryCard(
                    story,
                    tags=tags_lookup.get(str(story.get("id", ""))),
                )
                for story in by_state[state_key]
            ]
            column.set_cards(cards)

    def _restore_focus(self) -> None:
        """
        Re-focus the card at the active column/row after a refresh.

        If the previously-active card no longer exists, clamp to the
        last card in the column. Completely empty columns are left
        unfocused.
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
        Return the :class:`BoardColumn` at the given index.
        """
        state_key, _ = COLUMN_STATES[index]
        return self.query_one(f"#col-{state_key}", BoardColumn)

    def _focused_card(self) -> StoryCard | None:
        """
        Return the currently-focused card or ``None``.
        """
        column = self._column_at(self._active_col)
        cards = column.cards
        if not cards:
            return None
        self._active_row = max(0, min(self._active_row, len(cards) - 1))
        return cards[self._active_row]

    def _next_non_empty_column(self, start: int, step: int) -> int | None:
        """
        Return the next column index with at least one card.

        Walks ``step`` at a time from ``start`` (exclusive) and returns
        the first index whose column has cards, or ``None`` when no
        such column exists within the board bounds.
        """
        index = start + step
        while 0 <= index < len(COLUMN_STATES):
            if self._column_at(index).cards:
                return index
            index += step
        return None

    def action_focus_next_column(self) -> None:
        """
        Focus the next non-empty column's card at the same row.

        Columns with no cards are skipped so a sparse board does not
        force multiple ``l`` presses to step over gaps. A no-op when
        every column to the right is empty.
        """
        target = self._next_non_empty_column(self._active_col, 1)
        if target is None:
            return
        self._active_col = target
        card = self._focused_card()
        if card is not None:
            card.focus()

    def action_focus_prev_column(self) -> None:
        """
        Focus the previous non-empty column's card at the same row.

        Mirror of :meth:`action_focus_next_column`; no-ops when every
        column to the left is empty.
        """
        target = self._next_non_empty_column(self._active_col, -1)
        if target is None:
            return
        self._active_col = target
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

    def action_cancel_move_mode(self) -> None:
        """
        Leave move mode without transitioning.
        """
        if self._move_mode:
            self._move_mode = False
            self.notify("move cancelled")

    async def action_refresh_board(self) -> None:
        """
        Keybinding for ``r``.
        """
        await self.refresh_data()
        self.notify("board refreshed")

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

    def action_open_search(self) -> None:
        """
        Post :class:`OpenSearch` so the app can push the search
        screen on top of the current screen stack.
        """
        self.post_message(OpenSearch())

    async def action_show_help(self) -> None:
        """
        Push the shared help overlay with this screen's bindings.
        """
        await self.app.push_screen(KeybindingHelp(title="Board", bindings=HELP_ROWS))

    async def action_new_story(self) -> None:
        """
        Launch ``$EDITOR`` on a new-story template and POST the result.

        The template's first non-empty line becomes the title; anything
        after becomes the markdown description. Leaving the title line
        unchanged (or deleting everything) aborts with a flash so a
        stray ``n`` keypress never creates a junk story.
        """
        edited = await edit_markdown(
            self.app, NEW_STORY_TEMPLATE, runner=self._editor_runner
        )
        if edited is None:
            self.notify("new story aborted")
            return
        title, description = _split_new_story(edited)
        if not title or title == PLACEHOLDER_TITLE:
            self.notify("new story aborted: title unchanged")
            return
        client = self.app.client  # type: ignore[attr-defined]
        workspace_id = str(self._workspace.get("id", ""))
        payload: dict[str, Any] = {"title": title}
        if description:
            payload["description"] = description
        try:
            await client.post(f"/workspaces/{workspace_id}/stories", json=payload)
        except ApiError as exc:
            self.notify(f"new story failed: {exc}", severity="error")
            return
        self.notify(f"created story '{title}'")
        await self.refresh_data()

    def action_back(self) -> None:
        """
        Pop back to the workspace list.
        """
        self.app.pop_screen()

    async def on_key(self, event: events.Key) -> None:
        """
        Consume the next key when move mode is active.

        Runs before the Binding system because
        :meth:`Screen.on_key` is called first; returning without
        calling ``event.stop`` lets Textual fall through to bindings
        for normal keys.
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
        React to a WebSocket event. Any ``story.*`` event triggers a
        refetch so the board stays in sync without manual refresh.
        """
        event_type = str(event.get("event_type", ""))
        if event_type.startswith(STORY_EVENT_PREFIX):
            await self.refresh_data()


def _split_new_story(raw: str) -> tuple[str, str]:
    """
    Parse the new-story template output into (title, description).

    First non-empty, non-comment line wins as the title; a leading
    ``#`` is stripped so users can treat the template's markdown-style
    header as a hint rather than preserved prose. Everything after the
    title line becomes the description, leading blank lines trimmed so
    the body does not open with an empty paragraph.
    """
    lines = raw.splitlines()
    title: str | None = None
    description_lines: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if title is None:
            if not stripped:
                continue
            normalized = stripped
            if normalized.startswith("#"):
                normalized = normalized.lstrip("#").strip()
            title = normalized
            description_lines = lines[index + 1 :]
            break
    while description_lines and not description_lines[0].strip():
        description_lines.pop(0)
    while description_lines and not description_lines[-1].strip():
        description_lines.pop()
    description = "\n".join(description_lines)
    # Drop the second "# Description below" template marker if it
    # survived unmodified.
    if description.startswith("# Description below"):
        stripped_desc = description.split("\n", 1)
        description = stripped_desc[1].lstrip("\n") if len(stripped_desc) > 1 else ""
    return title or "", description
