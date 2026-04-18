"""
Global fuzzy search overlay (milestone 14).

Pressed from the workspace list or the board with ``/``. The screen
builds (lazily, on first open and cached for the rest of the session)
a client-side index of every visible story: (human_id, title, first
200 chars of description, workspace_key, state, id). Typing in the
input narrows the result table live; ``enter`` opens the story detail
for the highlighted row.

Ranking
-------

We deliberately avoid a hard runtime dependency on ``rapidfuzz``:
``difflib.SequenceMatcher`` from the standard library is more than
fast enough for the scale phase 1 targets (low thousands of stories,
local workspace). The scorer computes a weighted ratio over three
fields:

* ``human_id``   weight 0.40 (case-folded; exact and prefix matches
  earn a large bonus so typing ``KAN-12`` scrolls directly to that
  story).
* ``title``      weight 0.40
* ``description`` weight 0.20 (only the first 200 chars are indexed
  to keep scoring cheap on long descriptions).

A score under ``MIN_SCORE`` is dropped so the table never drowns the
user in irrelevant hits; an empty query shows the first N rows in the
index's insertion order, matching the spec's "no-input" landing.

Live updates
------------

Any ``story.*`` WS event invalidates the cached index so the next
open rebuilds from fresh data. Rebuilding in place while the screen
is open would risk racing with the user's current query; the cost of
a full refresh on re-entry is tiny (one paginated fetch per
workspace) and the code is dramatically simpler.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from kanberoo_tui.client import ApiError
from kanberoo_tui.messages import StorySelected

MAX_VISIBLE_RESULTS = 50
MIN_SCORE = 0.15
DESCRIPTION_PREFIX_LENGTH = 200

WEIGHT_HUMAN_ID = 0.40
WEIGHT_TITLE = 0.40
WEIGHT_DESCRIPTION = 0.20
PREFIX_BONUS = 0.35

STORY_EVENT_PREFIX = "story."


@dataclass
class IndexedStory:
    """
    One entry in the search index.

    Cached per story so scoring never re-walks the dict keys; the
    workspace key is resolved once on index build.
    """

    id: str
    human_id: str
    title: str
    workspace_key: str
    state: str
    description_prefix: str
    story: dict[str, Any]


def _score(query: str, entry: IndexedStory) -> float:
    """
    Return the ranked score for ``entry`` against ``query``.

    Blends a weighted average of human_id, title, and description
    similarity with a prefix-match bonus. Case-folded everywhere so
    the user never has to match casing to find anything. Returns 0
    for any entry missing all three fields, which cannot happen in
    normal operation but keeps the scorer well-defined.
    """
    q = query.strip().lower()
    if not q:
        return 1.0
    id_ratio = SequenceMatcher(None, q, entry.human_id.lower()).ratio()
    title_ratio = SequenceMatcher(None, q, entry.title.lower()).ratio()
    desc_ratio = SequenceMatcher(None, q, entry.description_prefix.lower()).ratio()
    total = (
        WEIGHT_HUMAN_ID * id_ratio
        + WEIGHT_TITLE * title_ratio
        + WEIGHT_DESCRIPTION * desc_ratio
    )
    if entry.human_id.lower().startswith(q) or entry.title.lower().startswith(q):
        total = min(1.0, total + PREFIX_BONUS)
    if q in entry.human_id.lower() or q in entry.title.lower():
        total = min(1.0, total + 0.2)
    return total


class SearchScreen(Screen[None]):
    """
    Full-screen fuzzy-search overlay.

    Owns the search input, the result table, and the shared index.
    The index is rebuilt on mount (or when invalidated by a
    ``story.*`` WS event) from ``/workspaces`` and
    ``/workspaces/{id}/stories``; every workspace contributes its own
    stories so search is genuinely global.
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
        Build an empty search screen. The index and results are
        populated on :meth:`on_mount`.
        """
        super().__init__()
        self._index: list[IndexedStory] = []
        self._ranked: list[IndexedStory] = []
        self._last_query: str = ""

    def compose(self) -> ComposeResult:
        """
        Lay out the input, result table, and footer.
        """
        yield Header()
        yield Input(placeholder="type to search (enter to open)...", id="search-input")
        yield Static(
            "0 results (building index)",
            id="search-hint",
            classes="search-hint",
        )
        yield Vertical(id="search-body")
        yield Footer()

    async def on_mount(self) -> None:
        """
        Build the table, subscribe to WS events, populate the index.
        """
        body = self.query_one("#search-body", Vertical)
        table: DataTable[str] = DataTable(
            id="search-table", cursor_type="row", zebra_stripes=True
        )
        table.add_columns("KEY", "TITLE", "WORKSPACE", "STATE")
        await body.mount(table)
        self.app.register_ws_listener(self)  # type: ignore[attr-defined]
        await self._build_index()
        self._rank_and_render("")
        self.query_one("#search-input", Input).focus()

    def on_unmount(self) -> None:
        """
        Deregister the WS listener.
        """
        self.app.unregister_ws_listener(self)  # type: ignore[attr-defined]

    async def _build_index(self) -> None:
        """
        Walk every workspace and build the client-side index.

        Each workspace contributes a fresh page-walk through
        ``/workspaces/{id}/stories``; the cost is one HTTP round-trip
        per workspace for the single-user scale phase 1 targets. A
        failure on any individual workspace skips that workspace and
        logs a notification; the index still contains everything else.
        """
        client = self.app.client  # type: ignore[attr-defined]
        try:
            workspace_response = await client.get("/workspaces", params={"limit": 200})
        except ApiError as exc:
            self.notify(f"search index failed: {exc}", severity="error")
            self._index = []
            return
        workspaces = list(workspace_response.json().get("items", []))
        index: list[IndexedStory] = []
        for workspace in workspaces:
            workspace_id = str(workspace.get("id", ""))
            workspace_key = str(workspace.get("key", ""))
            try:
                stories = await self._fetch_stories(client, workspace_id)
            except ApiError as exc:
                self.notify(
                    f"search: skipped {workspace_key}: {exc}", severity="warning"
                )
                continue
            for story in stories:
                description = (story.get("description") or "")[
                    :DESCRIPTION_PREFIX_LENGTH
                ]
                index.append(
                    IndexedStory(
                        id=str(story.get("id", "")),
                        human_id=str(story.get("human_id", "")),
                        title=str(story.get("title", "")),
                        workspace_key=workspace_key,
                        state=str(story.get("state", "")),
                        description_prefix=description,
                        story=story,
                    )
                )
        self._index = index

    async def _fetch_stories(
        self,
        client: Any,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """
        Walk a single workspace's stories endpoint cursor-paginated.
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

    def _rank_and_render(self, query: str) -> None:
        """
        Rank the index against ``query`` and rebuild the result table.
        """
        self._last_query = query
        if not query:
            ranked = list(self._index)[:MAX_VISIBLE_RESULTS]
        else:
            scored: list[tuple[float, IndexedStory]] = [
                (_score(query, entry), entry) for entry in self._index
            ]
            scored.sort(key=lambda pair: pair[0], reverse=True)
            ranked = [entry for score, entry in scored if score >= MIN_SCORE][
                :MAX_VISIBLE_RESULTS
            ]
        self._ranked = ranked
        table = self.query_one("#search-table", DataTable)
        table.clear()
        for entry in ranked:
            table.add_row(
                entry.human_id,
                entry.title,
                entry.workspace_key,
                entry.state,
                key=entry.id,
            )
        hint = self.query_one("#search-hint", Static)
        hint.update(
            f"{len(ranked)} result{'s' if len(ranked) != 1 else ''} "
            f"(index: {len(self._index)} stories)"
        )

    async def on_input_changed(self, message: Input.Changed) -> None:
        """
        Re-rank on every keystroke in the search input.
        """
        if message.input.id != "search-input":
            return
        self._rank_and_render(message.value)

    async def action_open_selected(self) -> None:
        """
        Open the story detail for the highlighted row.
        """
        if not self._ranked:
            return
        table = self.query_one("#search-table", DataTable)
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:  # noqa: BLE001
            return
        row_key = cell_key.row_key.value
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

    async def handle_ws_event(self, event: dict[str, Any]) -> None:
        """
        Rebuild the index on any ``story.*`` event so live changes
        show up in subsequent searches.
        """
        event_type = str(event.get("event_type", ""))
        if not event_type.startswith(STORY_EVENT_PREFIX):
            return
        await self._build_index()
        self._rank_and_render(self._last_query)

    @property
    def index(self) -> list[IndexedStory]:
        """
        Return a copy of the current index (for tests).
        """
        return list(self._index)

    @property
    def ranked(self) -> list[IndexedStory]:
        """
        Return the current ranked result list (for tests).
        """
        return list(self._ranked)
