"""
Session-wide search index behind the TUI's global ``/`` overlay.

The index is owned by :class:`~kanbaroo_tui.app.KanbarooTuiApp` and
lives for the whole session; :class:`~kanbaroo_tui.screens.search.SearchScreen`
only reads from it. That split is what makes reopening search free:
the screen renders whatever the index already holds and never issues
HTTP requests of its own.

Build phases
------------

A build runs in two phases so the user can start typing against
partial data instead of waiting for everything:

1. **Stories.** One ``/workspaces`` walk plus one paginated
   ``/workspaces/{id}/stories`` walk per workspace. Each story becomes
   an :class:`IndexedStory` carrying its human id, title, description
   prefix, workspace key, and state. Comment text from the previous
   build is carried over by story id so a refresh does not blank out
   comment hits between phases.
2. **Comments.** One paginated ``/workspaces/{id}/comments`` walk per
   workspace (the bulk endpoint added in server v0.5.0), grouped by
   ``story_id`` and capped per story. Servers that predate the route
   answer 404 without a workspace ``entity_type`` in the error
   details; the index then falls back to the per-story
   ``/stories/{id}/comments`` fetch for that build and remembers the
   verdict for the rest of the session so it does not keep probing.

Listeners registered with :meth:`SearchIndex.add_listener` are called
after each phase lands so an open screen can re-rank against the
current query.

Staleness and coalescing
------------------------

``story.*`` and ``comment.*`` WebSocket events mark the index stale.
The app debounces those into a single background refresh; this module
guarantees that two builds never run concurrently (a refresh requested
mid-build is remembered and run exactly once afterwards) and that a
cancelled or failed build leaves the index marked stale so the next
open retries.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from kanbaroo_tui.client import ApiError, ApiRequestError, AsyncApiClient

DESCRIPTION_PREFIX_LENGTH = 200
COMMENTS_PREFIX_LENGTH = 500
PAGE_LIMIT = 200

STORY_EVENT_PREFIX = "story."
COMMENT_EVENT_PREFIX = "comment."

IndexListener = Callable[[], None]
WarningSink = Callable[[str], None]


class IndexPhase(StrEnum):
    """
    Which part of a build is currently running. ``IDLE`` means no
    build is in progress.
    """

    IDLE = "idle"
    STORIES = "stories"
    COMMENTS = "comments"


@dataclass
class IndexedStory:
    """
    One entry in the search index.

    The lowercased copies of every searchable field are computed once
    here so the per-keystroke scorer never re-folds strings.
    """

    id: str
    human_id: str
    title: str
    workspace_key: str
    state: str
    description_prefix: str
    comments_blob: str
    story: dict[str, Any]
    human_id_lower: str = field(init=False, repr=False)
    title_lower: str = field(init=False, repr=False)
    description_lower: str = field(init=False, repr=False)
    comments_lower: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.human_id_lower = self.human_id.lower()
        self.title_lower = self.title.lower()
        self.description_lower = self.description_prefix.lower()
        self.comments_lower = self.comments_blob.lower()

    def set_comments(self, blob: str) -> None:
        """
        Replace the comment text (and its lowercased copy) in place.
        """
        self.comments_blob = blob
        self.comments_lower = blob.lower()


def is_search_relevant_event(event: dict[str, Any]) -> bool:
    """
    Return ``True`` for any ``story.*`` or ``comment.*`` WebSocket event.
    """
    event_type = str(event.get("event_type", ""))
    return event_type.startswith(STORY_EVENT_PREFIX) or event_type.startswith(
        COMMENT_EVENT_PREFIX
    )


def is_missing_route_404(exc: ApiRequestError) -> bool:
    """
    Decide whether a 404 from ``/workspaces/{id}/comments`` means the
    server has no such route (older release) rather than that the
    workspace does not exist.

    Both cases arrive in the canonical error envelope with code
    ``not_found``, so the status and code alone cannot tell them
    apart. They differ in ``details``: the service-layer
    ``NotFoundError`` for a missing or soft-deleted workspace carries
    ``{"entity_type": "workspace", "entity_id": ...}``, whereas
    Starlette's routing 404 reaches the error handler as a bare string
    and is rendered with ``details: null``. A reverse proxy answering
    with an HTML 404 parses to no details either. So a 404 whose
    details do not name a workspace entity is treated as "route not
    available on this server".
    """
    if exc.status_code != 404:
        return False
    details = exc.details or {}
    return details.get("entity_type") != "workspace"


def join_comment_bodies(bodies: list[str]) -> str:
    """
    Join comment bodies into the per-story searchable blob, capped to
    :data:`COMMENTS_PREFIX_LENGTH` characters.
    """
    return "\n".join(bodies)[:COMMENTS_PREFIX_LENGTH]


class SearchIndex:
    """
    Cached, incrementally refreshed index of every visible story.

    Instances are cheap to construct and hold no network state; the
    HTTP client is passed into :meth:`refresh` by the app so tests can
    drive the index with an :class:`httpx.MockTransport`-backed client
    and no Textual app at all.
    """

    def __init__(self) -> None:
        """
        Build an empty, stale, never-built index.
        """
        self._entries: list[IndexedStory] = []
        self._stale = True
        self._built = False
        self._comments_indexed = False
        self._phase = IndexPhase.IDLE
        self._building = False
        self._rebuild_requested = False
        self._listeners: list[IndexListener] = []
        self.bulk_comments_supported: bool | None = None
        self.on_warning: WarningSink | None = None
        self.build_count = 0

    @property
    def entries(self) -> list[IndexedStory]:
        """
        Return the current entries (a copy, so callers can iterate
        while a refresh swaps the underlying list).
        """
        return list(self._entries)

    @property
    def stale(self) -> bool:
        """
        ``True`` when a mutation event arrived since the last build
        started, or no build has succeeded yet.
        """
        return self._stale

    @property
    def built(self) -> bool:
        """
        ``True`` once the story phase of a build has completed at least
        once in this session.
        """
        return self._built

    @property
    def comments_indexed(self) -> bool:
        """
        ``True`` when the current entries carry comment text from a
        completed comment phase.
        """
        return self._comments_indexed

    @property
    def phase(self) -> IndexPhase:
        """
        The build phase currently running, or ``IDLE``.
        """
        return self._phase

    @property
    def building(self) -> bool:
        """
        ``True`` while :meth:`refresh` is running a build.
        """
        return self._building

    def mark_stale(self) -> None:
        """
        Flag the cached entries as possibly out of date.
        """
        self._stale = True

    def add_listener(self, listener: IndexListener) -> None:
        """
        Register ``listener`` to be called after each build phase lands.
        Idempotent.
        """
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: IndexListener) -> None:
        """
        Remove a previously registered listener. No-op if absent.
        """
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _warn(self, message: str) -> None:
        if self.on_warning is not None:
            self.on_warning(message)

    async def refresh(self, client: AsyncApiClient) -> None:
        """
        Run a build, then run exactly one more if another refresh was
        requested while it was in flight.

        Calling this while a build is already running does not start a
        second one: it records that a follow-up is needed and returns
        immediately. A build that fails or is cancelled leaves the
        index marked stale so the next open tries again.
        """
        if self._building:
            self._rebuild_requested = True
            return
        self._building = True
        try:
            while True:
                self._rebuild_requested = False
                self._stale = False
                await self._build_once(client)
                self.build_count += 1
                if not self._rebuild_requested:
                    break
        except BaseException:
            self._stale = True
            raise
        finally:
            self._building = False
            self._phase = IndexPhase.IDLE
            self._notify()

    async def _build_once(self, client: AsyncApiClient) -> None:
        """
        One full two-phase build. See the module docstring.
        """
        self._phase = IndexPhase.STORIES
        self._notify()
        try:
            workspaces = await self._fetch_pages(client, "/workspaces")
        except ApiError as exc:
            self._warn(f"search index failed: {exc}")
            self._stale = True
            return

        previous = {entry.id: entry for entry in self._entries}
        entries: list[IndexedStory] = []
        by_workspace: dict[str, list[IndexedStory]] = {}
        for workspace in workspaces:
            workspace_id = str(workspace.get("id", ""))
            workspace_key = str(workspace.get("key", ""))
            try:
                stories = await self._fetch_pages(
                    client, f"/workspaces/{workspace_id}/stories"
                )
            except ApiError as exc:
                self._warn(f"search: skipped {workspace_key}: {exc}")
                continue
            scoped: list[IndexedStory] = []
            for story in stories:
                story_id = str(story.get("id", ""))
                prior = previous.get(story_id)
                entry = IndexedStory(
                    id=story_id,
                    human_id=str(story.get("human_id", "")),
                    title=str(story.get("title", "")),
                    workspace_key=workspace_key,
                    state=str(story.get("state", "")),
                    description_prefix=(story.get("description") or "")[
                        :DESCRIPTION_PREFIX_LENGTH
                    ],
                    comments_blob=prior.comments_blob if prior is not None else "",
                    story=story,
                )
                entries.append(entry)
                scoped.append(entry)
            by_workspace[workspace_id] = scoped

        self._entries = entries
        self._built = True
        self._comments_indexed = False
        self._phase = IndexPhase.COMMENTS
        self._notify()

        for workspace_id, scoped in by_workspace.items():
            blobs = await self._fetch_comment_blobs(client, workspace_id, scoped)
            for entry in scoped:
                entry.set_comments(blobs.get(entry.id, ""))

        self._comments_indexed = True
        self._phase = IndexPhase.IDLE
        self._notify()

    async def _fetch_pages(
        self, client: AsyncApiClient, path: str
    ) -> list[dict[str, Any]]:
        """
        Walk a cursor-paginated list endpoint and return every item.
        """
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": PAGE_LIMIT}
            if cursor is not None:
                params["cursor"] = cursor
            response = await client.get(path, params=params)
            body = response.json()
            items.extend(body.get("items") or [])
            cursor = body.get("next_cursor")
            if cursor is None:
                break
        return items

    async def _fetch_comment_blobs(
        self,
        client: AsyncApiClient,
        workspace_id: str,
        scoped: list[IndexedStory],
    ) -> dict[str, str]:
        """
        Return ``{story_id: comments_blob}`` for every story in
        ``scoped``, preferring the bulk workspace endpoint and falling
        back to per-story fetches on servers that lack it.
        """
        if self.bulk_comments_supported is not False:
            try:
                blobs = await self._fetch_bulk_comment_blobs(client, workspace_id)
            except ApiRequestError as exc:
                if is_missing_route_404(exc):
                    self.bulk_comments_supported = False
                elif exc.status_code == 404:
                    # The workspace was deleted between phases; nothing
                    # to index for it.
                    return {}
                else:
                    self._warn(f"search: comments for workspace skipped: {exc}")
                    return {}
            except ApiError as exc:
                self._warn(f"search: comments for workspace skipped: {exc}")
                return {}
            else:
                self.bulk_comments_supported = True
                return blobs
        return {
            entry.id: await self._fetch_story_comment_blob(client, entry.id)
            for entry in scoped
            if entry.id
        }

    async def _fetch_bulk_comment_blobs(
        self, client: AsyncApiClient, workspace_id: str
    ) -> dict[str, str]:
        """
        Walk ``GET /workspaces/{id}/comments`` and group bodies by
        story id. Errors propagate so the caller can decide between
        fallback and skip.
        """
        bodies: dict[str, list[str]] = {}
        items = await self._fetch_pages(client, f"/workspaces/{workspace_id}/comments")
        for comment in items:
            if not isinstance(comment, dict):
                continue
            story_id = comment.get("story_id")
            body = comment.get("body")
            if not isinstance(story_id, str) or not isinstance(body, str) or not body:
                continue
            bodies.setdefault(story_id, []).append(body)
        return {
            story_id: join_comment_bodies(parts) for story_id, parts in bodies.items()
        }

    async def _fetch_story_comment_blob(
        self, client: AsyncApiClient, story_id: str
    ) -> str:
        """
        Legacy per-story comment fetch. A failure yields an empty blob
        so one bad story cannot poison the whole build.
        """
        try:
            response = await client.get(f"/stories/{story_id}/comments")
        except ApiError:
            return ""
        items = response.json().get("items") or []
        bodies = [
            comment["body"]
            for comment in items
            if isinstance(comment, dict)
            and isinstance(comment.get("body"), str)
            and comment["body"]
        ]
        return join_comment_bodies(bodies)
