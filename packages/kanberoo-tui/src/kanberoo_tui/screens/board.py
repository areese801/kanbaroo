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
from kanberoo_tui.widgets.duplicate_confirm import DuplicateConfirm
from kanberoo_tui.widgets.help_modal import KeybindingHelp
from kanberoo_tui.widgets.story_card import StoryCard
from kanberoo_tui.widgets.tag_filter import TagFilterPicker

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

STATE_PROGRESSION: list[str] = [
    "backlog",
    "todo",
    "in_progress",
    "in_review",
    "done",
]

SORT_MODE_ID_ASC = "id-asc"
SORT_MODE_PRIORITY_DESC = "priority-desc"

SORT_MODE_CYCLE: list[str] = [SORT_MODE_ID_ASC, SORT_MODE_PRIORITY_DESC]

PRIORITY_RANK: dict[str, int] = {
    "high": 0,
    "medium": 1,
    "low": 2,
    "none": 3,
}

_ID_SUFFIX_MAX = 10**12


def _id_suffix(human_id: str) -> int:
    """
    Return the numeric suffix of a ``KAN-N`` style id, or
    :data:`sys.maxsize` when the id is malformed.

    Used as the secondary sort key in priority mode and the primary
    sort key in id-asc mode so a sparse id range stays in its natural
    order (KAN-2 before KAN-10).
    """
    if not human_id:
        return _ID_SUFFIX_MAX
    _, _, tail = human_id.rpartition("-")
    if not tail.isdigit():
        return _ID_SUFFIX_MAX
    return int(tail)


def sort_stories(
    stories: list[dict[str, Any]],
    mode: str,
) -> list[dict[str, Any]]:
    """
    Return ``stories`` ordered according to ``mode``.

    ``id-asc`` sorts by the numeric suffix of ``human_id`` ascending
    (the historical default). ``priority-desc`` sorts by priority
    bucket (high, medium, low, none) breaking ties on the same id
    suffix. Unknown modes fall back to ``id-asc`` so the board never
    renders blank.
    """
    if mode == SORT_MODE_PRIORITY_DESC:
        return sorted(
            stories,
            key=lambda s: (
                PRIORITY_RANK.get(str(s.get("priority", "none")), len(PRIORITY_RANK)),
                _id_suffix(str(s.get("human_id", ""))),
            ),
        )
    return sorted(
        stories,
        key=lambda s: _id_suffix(str(s.get("human_id", ""))),
    )


def next_forward_state(current: str) -> str | None:
    """
    Return the next natural state after ``current``.

    Mirrors the CLI helper so the TUI quick-advance keybinding and
    ``kb story move`` share one progression. Returns ``None`` when
    ``current`` is ``done`` (or an unknown state); callers flash a
    no-op message instead of wrapping back to ``backlog``.
    """
    try:
        index = STATE_PROGRESSION.index(current)
    except ValueError:
        return None
    if index + 1 >= len(STATE_PROGRESSION):
        return None
    return STATE_PROGRESSION[index + 1]


STORY_EVENT_PREFIX = "story."

NEW_STORY_TEMPLATE = "# Title (replace this line)\n\n# Description below\n\n"

PLACEHOLDER_TITLE = "Title (replace this line)"

HELP_ROWS: list[tuple[str, str]] = [
    ("h / l / \u2190 / \u2192", "move between columns"),
    ("j / k / \u2193 / \u2191", "move within a column"),
    ("enter", "open story detail"),
    ("m then b/t/p/r/d", "move the focused card"),
    (">", "advance the focused card one step"),
    ("n", "new story via $EDITOR"),
    ("/", "fuzzy search"),
    ("f", "filter by tag"),
    ("F", "clear tag filter"),
    ("s", "cycle sort mode (id / priority)"),
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
        Binding(
            "greater_than_sign",
            "quick_advance",
            "Advance",
            priority=True,
        ),
        Binding("enter", "open_detail", "Detail"),
        Binding("n", "new_story", "New"),
        Binding("slash", "open_search", "Search", show=False),
        Binding("f", "open_tag_filter", "Filter", priority=True),
        Binding("F", "clear_tag_filter", "Clear filter", priority=True),
        Binding("s", "cycle_sort", "Sort", priority=True),
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
        # Active tag filter: list of (tag_id, tag_name) tuples. Empty
        # means "no filter, show all". The tag_name is used to drive
        # the server-side ``?tag=`` filter (one fetch per tag, then
        # union); the tag_id is what the picker round-trips so the
        # selection survives reopen.
        self._active_tag_filter: list[tuple[str, str]] = []
        self._sort_mode: str = SORT_MODE_ID_ASC

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

    @property
    def active_tag_filter(self) -> list[tuple[str, str]]:
        """
        Return the active ``(tag_id, tag_name)`` filter; empty means
        "no filter active".
        """
        return list(self._active_tag_filter)

    @property
    def sort_mode(self) -> str:
        """
        Return the active sort mode (``id-asc`` or ``priority-desc``).
        """
        return self._sort_mode

    async def on_mount(self) -> None:
        """
        Register as the WS listener and load the board data.
        """
        self._update_sub_title()
        self.app.register_ws_listener(self)  # type: ignore[attr-defined]
        await self.refresh_data()

    def _update_sub_title(self) -> None:
        """
        Recompute the screen sub_title to reflect any active filter
        and non-default sort mode.
        """
        key = str(self._workspace.get("key", ""))
        parts: list[str] = []
        if key:
            parts.append(f"{key} - Board")
        else:
            parts.append("Board")
        if self._active_tag_filter:
            tags = ", ".join(name for _id, name in self._active_tag_filter)
            parts.append(f"filter: {tags}")
        if self._sort_mode != SORT_MODE_ID_ASC:
            parts.append(f"sort: {self._sort_mode_label()}")
        self.sub_title = "  |  ".join(parts)

    def _sort_mode_label(self) -> str:
        """
        Return a short human-readable label for the current sort
        mode, used in the header chip.
        """
        if self._sort_mode == SORT_MODE_PRIORITY_DESC:
            return "priority"
        return "id"

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
        pair. When :attr:`_active_tag_filter` is non-empty the fetch
        is partitioned per tag (one call each) and the union is
        rendered.
        """
        client = self.app.client  # type: ignore[attr-defined]
        workspace_id = str(self._workspace.get("id", ""))
        try:
            if self._active_tag_filter:
                stories = await self._fetch_stories_by_tags(
                    client,
                    workspace_id,
                    [name for _id, name in self._active_tag_filter],
                )
            else:
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

    async def _fetch_stories_by_tags(
        self,
        client: Any,
        workspace_id: str,
        tag_names: list[str],
    ) -> list[dict[str, Any]]:
        """
        Fetch stories matching any of ``tag_names`` and return the
        deduplicated union.

        The list endpoint accepts a single ``?tag=name`` filter, so
        the union is computed client-side: one paginated walk per
        tag, then dedup by story id keeping insertion order.
        """
        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for tag_name in tag_names:
            cursor: str | None = None
            while True:
                params: dict[str, Any] = {"limit": 200, "tag": tag_name}
                if cursor is not None:
                    params["cursor"] = cursor
                response = await client.get(
                    f"/workspaces/{workspace_id}/stories",
                    params=params,
                )
                body = response.json()
                for story in body.get("items", []):
                    story_id = str(story.get("id", ""))
                    if story_id and story_id not in seen:
                        seen.add(story_id)
                        merged.append(story)
                cursor = body.get("next_cursor")
                if cursor is None:
                    break
        return merged

    def _render_columns(self) -> None:
        """
        Distribute stories into columns by state, applying the active
        sort mode within each column.
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
            ordered = sort_stories(by_state[state_key], self._sort_mode)
            cards = [
                StoryCard(
                    story,
                    tags=tags_lookup.get(str(story.get("id", ""))),
                )
                for story in ordered
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

    async def action_open_tag_filter(self) -> None:
        """
        Open the tag-filter modal and apply the chosen filter.

        Fetches the workspace tags fresh on each open so newly
        created tags appear without a board refresh. The picker
        dismisses with ``None`` (escape, no change), an empty list
        (clear filter), or a list of ``(tag_id, name)`` tuples
        (apply). The dismiss callback handles each case so the
        action method itself does not block on the modal.
        """
        client = self.app.client  # type: ignore[attr-defined]
        workspace_id = str(self._workspace.get("id", ""))
        try:
            response = await client.get(f"/workspaces/{workspace_id}/tags")
        except ApiError as exc:
            self.notify(f"tag fetch failed: {exc}", severity="error")
            return
        tags = list(response.json().get("items", []))
        initial_ids = {tag_id for tag_id, _ in self._active_tag_filter}

        async def _on_dismiss(chosen: list[tuple[str, str]] | None) -> None:
            if chosen is None:
                return
            self._active_tag_filter = list(chosen)
            self._update_sub_title()
            if not chosen:
                self.notify("filter cleared")
            else:
                names = ", ".join(name for _id, name in chosen)
                self.notify(f"filter: {names}")
            await self.refresh_data()

        await self.app.push_screen(
            TagFilterPicker(tags=tags, initial_tag_ids=initial_ids),
            _on_dismiss,
        )

    async def action_clear_tag_filter(self) -> None:
        """
        Clear the active tag filter and refresh the board.
        """
        if not self._active_tag_filter:
            self.notify("no filter active")
            return
        self._active_tag_filter = []
        self._update_sub_title()
        self.notify("filter cleared")
        await self.refresh_data()

    def action_cycle_sort(self) -> None:
        """
        Cycle through the supported sort modes.
        """
        try:
            index = SORT_MODE_CYCLE.index(self._sort_mode)
        except ValueError:
            index = 0
        self._sort_mode = SORT_MODE_CYCLE[(index + 1) % len(SORT_MODE_CYCLE)]
        self._update_sub_title()
        self._render_columns()
        self._restore_focus()
        self.notify(f"sort: {self._sort_mode_label()}")

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

        Before posting we ask the server for stories with a normalised
        title equivalent to the proposed one. Any matches push a
        :class:`DuplicateConfirm` modal so the user can abort the
        likely duplicate; the create POST runs from the modal's
        dismiss callback so the action method can return cleanly
        without requiring an active worker.
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
        try:
            similar_response = await client.get(
                f"/workspaces/{workspace_id}/stories/similar",
                params={"title": title},
            )
            similar = list(similar_response.json().get("items", []))
        except ApiError as exc:
            self.notify(f"similar check failed: {exc}", severity="error")
            return
        if not similar:
            await self._post_new_story(title, description)
            return

        async def _on_dismiss(confirmed: bool | None) -> None:
            if not confirmed:
                self.notify("cancelled: similar story exists")
                return
            await self._post_new_story(title, description)

        await self.app.push_screen(
            DuplicateConfirm(entity="story", items=similar),
            _on_dismiss,
        )

    async def _post_new_story(self, title: str, description: str) -> None:
        """
        POST the create payload, notify, and refetch the board.
        """
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

    async def action_quick_advance(self) -> None:
        """
        Advance the focused card one step along the natural progression.

        Pressing ``>`` saves the two-keystroke ``m`` then ``t``/``p``/
        ``r``/``d`` dance for the common "move to the next column" case.
        A card already in ``done`` flashes a no-op message rather than
        wrapping back to ``backlog``.
        """
        card = self._focused_card()
        if card is None:
            self.notify("no card focused")
            return
        story = card.story
        current_state = str(story.get("state", ""))
        human_id = str(story.get("human_id", "?"))
        if current_state == "done":
            self.notify(f"{human_id} is already done")
            return
        target = next_forward_state(current_state)
        if target is None:
            self.notify(f"no natural next state from {current_state!r}")
            return
        await self._transition_focused(target)

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
