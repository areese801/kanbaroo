"""
Global fuzzy search overlay (milestone 14).

Pressed from any screen with ``/``. The screen is a thin view over
the app-owned :class:`~kanbaroo_tui.search_index.SearchIndex`, which
lives for the whole session: opening search with a warm index renders
results immediately and issues zero HTTP requests. If the index has
never been built, or a ``story.*`` / ``comment.*`` WebSocket event
marked it stale, the screen renders whatever is cached and asks the
app to refresh in the background; each build phase (stories, then
comments) re-ranks the table against the current query as it lands.
The hint line under the input says which phase is running.

The input is focused the moment the screen mounts; nothing in
``on_mount`` waits on the network.

Ranking
-------

We deliberately avoid a hard runtime dependency on ``rapidfuzz``:
``difflib.SequenceMatcher`` from the standard library is fast enough
for the short fields it is applied to. Every searchable field is
lowercased once at index time. The scorer blends:

* ``human_id``   fuzzy ratio, weight 0.35, plus a large bonus for a
  prefix match. An exact match of the stripped, case-folded query
  against the human id is ranked ahead of every other entry outright,
  independent of score, so typing ``KAN-2`` always lands on ``KAN-2``
  rather than on ``KAN-24`` or on a story whose description quotes
  ``KAN-2`` (scores are capped at 1.0, so the bonuses alone cannot
  guarantee that).
* ``title``      fuzzy ratio, weight 0.35, with the same prefix and
  substring bonuses.
* ``description`` plain substring check on the first 200 chars;
  contributes a fixed weight when the query appears.
* ``comments``   plain substring check on the concatenated comment
  bodies (capped to 500 chars per story); fixed weight on a hit, which
  is what surfaces stories whose only signal lives in a comment thread.

Running ``SequenceMatcher`` over the long description and comment
blobs on every keystroke was the expensive part of the old scorer and
gave a weak fuzzy signal anyway; substring checks are both cheaper
and more predictable for those fields.

A score under ``MIN_SCORE`` is dropped so the table never drowns the
user in irrelevant hits; an empty query shows the first N rows in the
index's insertion order, matching the spec's "no-input" landing.
Re-ranking is debounced by a short timer that resets on every
keystroke; ``enter`` flushes any pending re-rank first so the row the
user opens always reflects what they typed.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Input, Static

from kanbaroo_tui.messages import StorySelected
from kanbaroo_tui.search_index import IndexedStory, IndexPhase, SearchIndex

__all__ = ["IndexedStory", "SearchScreen", "MAX_VISIBLE_RESULTS", "MIN_SCORE"]

MAX_VISIBLE_RESULTS = 50
MIN_SCORE = 0.15
RERANK_DEBOUNCE_SECONDS = 0.1

WEIGHT_HUMAN_ID = 0.35
WEIGHT_TITLE = 0.35
WEIGHT_DESCRIPTION = 0.2
WEIGHT_COMMENTS = 0.25
PREFIX_BONUS = 0.35
SUBSTRING_BONUS = 0.2


def _score(query: str, entry: IndexedStory) -> float:
    """
    Return the ranked score for ``entry`` against ``query``.

    Fuzzy-matches the two short fields (human id, title), adds fixed
    weights for substring hits in the description and comment blobs,
    and layers the prefix and substring bonuses on top. Case-folded
    everywhere via the entry's precomputed lowercase fields so the
    user never has to match casing to find anything.
    """
    q = query.strip().lower()
    if not q:
        return 1.0
    total = WEIGHT_HUMAN_ID * SequenceMatcher(None, q, entry.human_id_lower).ratio()
    total += WEIGHT_TITLE * SequenceMatcher(None, q, entry.title_lower).ratio()
    if q in entry.description_lower:
        total += WEIGHT_DESCRIPTION
    if q in entry.comments_lower:
        total += WEIGHT_COMMENTS
    if entry.human_id_lower.startswith(q) or entry.title_lower.startswith(q):
        total += PREFIX_BONUS
    if q in entry.human_id_lower or q in entry.title_lower:
        total += SUBSTRING_BONUS
    return min(1.0, total)


def rank_entries(query: str, entries: list[IndexedStory]) -> list[IndexedStory]:
    """
    Rank ``entries`` against ``query``, dropping anything under
    :data:`MIN_SCORE` and capping at :data:`MAX_VISIBLE_RESULTS`.

    Entries whose human id exactly equals the stripped, case-folded
    query sort ahead of everything else; the rest sort by score. An
    empty query returns the leading entries in index order.
    """
    q = query.strip().lower()
    if not q:
        return list(entries)[:MAX_VISIBLE_RESULTS]
    scored = [
        (entry.human_id_lower == q, _score(query, entry), entry) for entry in entries
    ]
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [entry for exact, score, entry in scored if exact or score >= MIN_SCORE][
        :MAX_VISIBLE_RESULTS
    ]


class SearchScreen(Screen[None]):
    """
    Full-screen fuzzy-search overlay.

    Owns the search input and the result table. The index itself is
    owned by the app (``app.search_index``); the screen subscribes to
    its phase notifications while mounted and re-ranks on each one.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
        Binding("enter", "open_selected", "Open", priority=True),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("ctrl+j", "cursor_down", "Down", show=False),
        Binding("ctrl+k", "cursor_up", "Up", show=False),
    ]

    DEFAULT_CSS = """
    SearchScreen {
        layout: vertical;
    }
    SearchScreen Input {
        margin: 1 2;
    }
    SearchScreen DataTable {
        height: 1fr;
    }
    SearchScreen .search-hint {
        padding: 0 2;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        """
        Build an empty search screen. The index is resolved from the
        app on :meth:`on_mount`.
        """
        super().__init__()
        self._index: SearchIndex | None = None
        self._ranked: list[IndexedStory] = []
        self._last_query: str = ""
        self._pending_query: str | None = None
        self._rerank_timer: Timer | None = None
        self._hint_text_value: str = "0 results"

    def compose(self) -> ComposeResult:
        """
        Lay out the input, result table, and footer.
        """
        yield Header()
        yield Input(placeholder="type to search (enter to open)...", id="search-input")
        yield Static("0 results", id="search-hint", classes="search-hint")
        yield Vertical(id="search-body")
        yield Footer()

    async def on_mount(self) -> None:
        """
        Mount the table, focus the input, render the cached index, and
        request a background refresh if the cache is cold or stale.
        """
        self.sub_title = "Search"
        body = self.query_one("#search-body", Vertical)
        table: DataTable[str] = DataTable(
            id="search-table", cursor_type="row", zebra_stripes=True
        )
        table.add_columns("KEY", "TITLE", "WORKSPACE", "STATE")
        await body.mount(table)
        self.query_one("#search-input", Input).focus()
        index: SearchIndex = self.app.search_index  # type: ignore[attr-defined]
        self._index = index
        index.add_listener(self._on_index_updated)
        self._rank_and_render("")
        if index.stale or not index.built:
            self.app.request_search_index_refresh()  # type: ignore[attr-defined]

    def on_unmount(self) -> None:
        """
        Unsubscribe from index notifications and drop any pending
        re-rank timer.
        """
        if self._index is not None:
            self._index.remove_listener(self._on_index_updated)
        if self._rerank_timer is not None:
            self._rerank_timer.stop()
            self._rerank_timer = None

    def _on_index_updated(self) -> None:
        """
        Index phase callback: apply any pending keystrokes, then re-rank
        the current query against the refreshed entries.

        No mounted-state guard: :meth:`on_unmount` removes this listener,
        and a build can finish while the screen is still inside its own
        mount handling (Textual reports ``is_mounted`` false there), so
        gating on it would drop the very notification that fills the
        table on first open.
        """
        self.flush_pending_rerank()
        self._rank_and_render(self._last_query, preserve_cursor=True)

    def _highlighted_story_id(self, table: DataTable[str]) -> str | None:
        """
        Return the row key (story id) under the table cursor, or
        ``None`` when the table is empty.
        """
        if table.row_count == 0:
            return None
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:  # noqa: BLE001
            return None
        value = cell_key.row_key.value
        return str(value) if value is not None else None

    def _rank_and_render(self, query: str, *, preserve_cursor: bool = False) -> None:
        """
        Rank the index against ``query`` and rebuild the result table.

        ``preserve_cursor`` is set for re-renders caused by an index
        update (same query the user is already looking at). Background
        refreshes fire several notifications per build and each table
        rebuild would otherwise reset the cursor to row 0, so the
        highlighted story is captured first and the cursor moved back
        to it if it is still in the ranked list. Re-ranking for a new
        query leaves the cursor at the top, which is the expected
        "best match first" behavior.
        """
        self._last_query = query
        entries = self._index.entries if self._index is not None else []
        ranked = rank_entries(query, entries)
        self._ranked = ranked
        table: DataTable[str] = self.query_one("#search-table", DataTable)
        highlighted = self._highlighted_story_id(table) if preserve_cursor else None
        table.clear()
        for entry in ranked:
            table.add_row(
                entry.human_id,
                entry.title,
                entry.workspace_key,
                entry.state,
                key=entry.id,
            )
        if highlighted is not None:
            row = next(
                (i for i, entry in enumerate(ranked) if entry.id == highlighted),
                None,
            )
            if row is not None:
                table.move_cursor(row=row)
        self._hint_text_value = self._hint_text(len(ranked), len(entries))
        self.query_one("#search-hint", Static).update(self._hint_text_value)

    def _hint_text(self, result_count: int, index_size: int) -> str:
        """
        Build the status line under the input, reflecting build phase.
        """
        base = f"{result_count} result{'s' if result_count != 1 else ''}"
        index = self._index
        if index is None or not index.built:
            return f"{base} (indexing stories...)"
        detail = f"index: {index_size} stories"
        if index.phase == IndexPhase.STORIES:
            detail += ", refreshing..."
        elif index.phase == IndexPhase.COMMENTS:
            detail += ", indexing comments..."
        return f"{base} ({detail})"

    async def on_input_changed(self, message: Input.Changed) -> None:
        """
        Record the new query and (re)start the debounce timer.
        """
        if message.input.id != "search-input":
            return
        self._pending_query = message.value
        if self._rerank_timer is not None:
            self._rerank_timer.stop()
        self._rerank_timer = self.set_timer(
            RERANK_DEBOUNCE_SECONDS, self._on_rerank_timer
        )

    def _on_rerank_timer(self) -> None:
        self._rerank_timer = None
        self.flush_pending_rerank()

    def flush_pending_rerank(self) -> None:
        """
        Apply any keystrokes the debounce timer has not yet flushed.

        Called before acting on ``enter`` so the highlighted row always
        corresponds to the typed query, and by tests that want
        deterministic ranking without waiting on the timer.
        """
        if self._rerank_timer is not None:
            self._rerank_timer.stop()
            self._rerank_timer = None
        if self._pending_query is None:
            return
        query = self._pending_query
        self._pending_query = None
        self._rank_and_render(query)

    async def action_open_selected(self) -> None:
        """
        Open the story detail for the highlighted row.
        """
        self.flush_pending_rerank()
        if not self._ranked:
            return
        row_key = self._highlighted_story_id(self.query_one("#search-table", DataTable))
        if row_key is None:
            return
        story = next(
            (entry.story for entry in self._ranked if entry.id == row_key),
            None,
        )
        if story is None:
            return
        self.app.pop_screen()
        self.post_message(StorySelected(story))

    def action_cursor_down(self) -> None:
        """
        Move the result cursor down without leaving the search input.
        """
        self.query_one("#search-table", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        """
        Move the result cursor up without leaving the search input.
        """
        self.query_one("#search-table", DataTable).action_cursor_up()

    def action_back(self) -> None:
        """
        Pop back to the caller.
        """
        self.app.pop_screen()

    @property
    def index(self) -> list[IndexedStory]:
        """
        Return a copy of the current index entries (for tests).
        """
        return self._index.entries if self._index is not None else []

    @property
    def ranked(self) -> list[IndexedStory]:
        """
        Return the current ranked result list (for tests).
        """
        return list(self._ranked)

    @property
    def hint_text(self) -> str:
        """
        Return the current hint line text (for tests).
        """
        return self._hint_text_value
