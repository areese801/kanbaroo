"""
Baseline SVG snapshot coverage for the Kanbaroo TUI.

Every test in this module exercises :func:`snap_compare` from
``pytest-textual-snapshot``: on first run each test writes an SVG
baseline under ``__snapshots__/``; on subsequent runs the SVG is
diffed against the committed baseline and any visual regression fails
the test. Regenerate baselines with ``uv run pytest --snapshot-update
packages/kanbaroo-tui/tests/test_snapshots.py``.

Two host shapes
---------------

* **Screens** are rendered through a full :class:`KanbarooTuiApp` with
  the same ``MockApi`` / ``FakeWsStream`` fixtures the pilot tests use.
  The test calls :func:`snap_compare` with a ``run_before`` that presses
  keys to navigate to the target screen.
* **Modals** are hosted by a minimal :class:`_ModalHost` app that
  pushes the modal directly on mount. This keeps the snapshot scoped to
  the modal's own chrome without having to thread the full app's
  endpoint fixtures through a setup dance that is irrelevant to the
  modal's appearance.

Deterministic data
------------------

Every snapshot uses fixed human ids, titles, timestamps, and actor
strings so the SVG is byte-stable across runs. ``deleted_at: None``
and ``version: 1`` are carried for schema fidelity but not visually
significant.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from kanbaroo_tui.app import KanbarooTuiApp
from kanbaroo_tui.client import AsyncApiClient
from kanbaroo_tui.config import TuiConfig
from kanbaroo_tui.widgets.duplicate_confirm import DuplicateConfirm
from kanbaroo_tui.widgets.help_modal import KeybindingHelp
from kanbaroo_tui.widgets.link_picker import LinkPicker
from kanbaroo_tui.widgets.tag_filter import TagFilterPicker
from kanbaroo_tui.widgets.tag_picker import TagPicker

SCREEN_SIZE: tuple[int, int] = (120, 40)
MODAL_SIZE: tuple[int, int] = (80, 24)


def _workspace(
    id_: str = "ws-1",
    key: str = "KAN",
    name: str = "Kanbaroo",
    *,
    updated_at: str = "2026-04-18T00:00:00Z",
) -> dict[str, Any]:
    return {
        "id": id_,
        "key": key,
        "name": name,
        "description": None,
        "next_issue_num": 1,
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": updated_at,
        "deleted_at": None,
        "version": 1,
    }


def _story(
    id_: str,
    human_id: str,
    *,
    title: str = "A story",
    state: str = "backlog",
    priority: str = "none",
    epic_id: str | None = None,
    version: int = 1,
) -> dict[str, Any]:
    return {
        "id": id_,
        "workspace_id": "ws-1",
        "epic_id": epic_id,
        "human_id": human_id,
        "title": title,
        "description": None,
        "priority": priority,
        "state": state,
        "state_actor_type": None,
        "state_actor_id": None,
        "branch_name": None,
        "commit_sha": None,
        "pr_url": None,
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": "2026-04-17T00:00:00Z",
        "deleted_at": None,
        "version": version,
    }


def _epic(
    id_: str,
    human_id: str,
    *,
    title: str = "An epic",
    state: str = "open",
) -> dict[str, Any]:
    return {
        "id": id_,
        "workspace_id": "ws-1",
        "human_id": human_id,
        "title": title,
        "description": None,
        "state": state,
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": "2026-04-17T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def _tag(id_: str, name: str, *, color: str = "#00ff88") -> dict[str, Any]:
    return {
        "id": id_,
        "workspace_id": "ws-1",
        "name": name,
        "color": color,
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": "2026-04-17T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def _list_body(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"items": items, "next_cursor": None}


def _audit_event(
    event_id: str,
    *,
    action: str = "created",
    entity_type: str = "story",
    entity_id: str = "story-1",
    actor_type: str = "human",
    actor_id: str = "adam",
    occurred_at: str = "2026-04-18T00:00:00Z",
    diff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": event_id,
        "occurred_at": occurred_at,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "entity_version": 1,
    }
    if diff is not None:
        body["diff"] = diff
    return body


def _seed_workspace_list(
    mock_api: Any,
    *,
    workspaces: list[dict[str, Any]] | None = None,
    counts: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> None:
    """
    Seed ``GET /workspaces`` and its story/epic count dependents.

    ``counts`` maps workspace id to ``(stories, epics)`` for the two
    count-probing GETs the workspace list fires per workspace. A
    workspace absent from ``counts`` gets empty probes so the row
    shows ``0 / 0``.
    """
    items = workspaces if workspaces is not None else [_workspace()]
    mock_api.json("GET", "/workspaces", body=_list_body(items))
    count_map = counts or {}
    for workspace in items:
        ws_id = str(workspace["id"])
        stories, epics = count_map.get(ws_id, ([], []))
        mock_api.json("GET", f"/workspaces/{ws_id}/stories", body=_list_body(stories))
        mock_api.json("GET", f"/workspaces/{ws_id}/epics", body=_list_body(epics))


@pytest.fixture
def app_factory(
    tui_config: TuiConfig,
    client_factory: Callable[[TuiConfig], AsyncApiClient],
    ws_factory: Callable[[TuiConfig], AsyncIterator[dict[str, Any]]],
    fake_editor: Any,
) -> Callable[..., KanbarooTuiApp]:
    """
    Build a :class:`KanbarooTuiApp` pre-wired to the fixture-scoped
    fakes. Used by every screen-level snapshot test.
    """

    def _factory(**overrides: Any) -> KanbarooTuiApp:
        return KanbarooTuiApp(
            config=tui_config,
            client_factory=overrides.pop("client_factory", client_factory),
            ws_factory=overrides.pop("ws_factory", ws_factory),
            editor_runner=overrides.pop("editor_runner", fake_editor),
        )

    return _factory


class _ModalHost(App[None]):
    """
    Minimal Textual host that pushes a modal on mount.

    ``modal_factory`` is invoked with the host instance and must
    return the modal screen to push. Keeping the host trivially small
    means a modal snapshot reflects the modal's own chrome rather than
    whatever host screen happens to be underneath it in production.
    """

    def __init__(
        self,
        modal_factory: Callable[[_ModalHost], Any],
    ) -> None:
        super().__init__()
        self._modal_factory = modal_factory

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        await self.push_screen(self._modal_factory(self))


def _modal_host_client() -> AsyncApiClient:
    """
    Build a dummy :class:`AsyncApiClient` for modals that accept one.

    The modals that need a client (tag picker, link picker) only touch
    it when the user presses enter inside the modal; a snapshot stops
    before that fires, so we just hand over a client with a transport
    that would 404 if accidentally called.
    """

    def _fallback(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"code": "not_found", "message": "stub"})

    return AsyncApiClient(
        base_url="http://test.invalid",
        token="kbr_test",
        transport=httpx.MockTransport(_fallback),
    )


# ---------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------


def test_snapshot_workspace_list(snap_compare, mock_api, app_factory):
    """
    WorkspaceListScreen rendered with two seeded workspaces.
    """
    _seed_workspace_list(
        mock_api,
        workspaces=[
            _workspace("ws-1", "KAN", "Kanbaroo"),
            _workspace(
                "ws-2",
                "ENG",
                "Engineering",
                updated_at="2026-04-18T12:00:00Z",
            ),
        ],
        counts={
            "ws-1": (
                [_story("story-1", "KAN-1"), _story("story-2", "KAN-2")],
                [_epic("epic-1", "KAN-E1")],
            ),
            "ws-2": ([_story("story-3", "ENG-1")], []),
        },
    )
    assert snap_compare(app_factory(), terminal_size=SCREEN_SIZE)


def test_snapshot_board(snap_compare, mock_api, app_factory):
    """
    BoardScreen with cards in every column.
    """
    _seed_workspace_list(
        mock_api,
        counts={
            "ws-1": (
                [
                    _story("story-1", "KAN-1", state="backlog"),
                    _story("story-2", "KAN-2", state="todo", priority="high"),
                    _story("story-3", "KAN-3", state="in_progress"),
                    _story("story-4", "KAN-4", state="in_review"),
                    _story("story-5", "KAN-5", state="done"),
                ],
                [],
            ),
        },
    )
    # Board re-fetches stories when opened.
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body=_list_body(
            [
                _story("story-1", "KAN-1", state="backlog", title="Wire the board"),
                _story(
                    "story-2",
                    "KAN-2",
                    state="todo",
                    title="Pick a sprint name",
                    priority="high",
                ),
                _story(
                    "story-3",
                    "KAN-3",
                    state="in_progress",
                    title="Ship snapshot tests",
                ),
                _story(
                    "story-4",
                    "KAN-4",
                    state="in_review",
                    title="Audit fixture",
                ),
                _story("story-5", "KAN-5", state="done", title="Hello world"),
            ]
        ),
    )

    async def _run(pilot: Any) -> None:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

    assert snap_compare(app_factory(), run_before=_run, terminal_size=SCREEN_SIZE)


def test_snapshot_story_detail_description(snap_compare, mock_api, app_factory):
    """
    StoryDetailScreen landing on the Description tab.
    """
    story = _story(
        "story-1",
        "KAN-1",
        title="Write snapshot tests",
        priority="high",
    )
    story["description"] = (
        "# Goal\n\nLock TUI appearance with SVG snapshots.\n\n"
        "- baseline coverage\n- regression guard\n"
    )
    _seed_workspace_list(
        mock_api,
        counts={"ws-1": ([story], [])},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body=_list_body([story]),
    )
    # Story detail fetches body, comments, linkages, and audit.
    mock_api.json("GET", "/stories/story-1", body=story)
    mock_api.json("GET", "/stories/story-1/comments", body=_list_body([]))
    mock_api.json("GET", "/stories/story-1/linkages", body=_list_body([]))
    mock_api.json(
        "GET",
        "/audit/entity/story/story-1",
        body=_list_body([]),
    )

    async def _run(pilot: Any) -> None:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

    assert snap_compare(app_factory(), run_before=_run, terminal_size=SCREEN_SIZE)


def test_snapshot_story_detail_comments(snap_compare, mock_api, app_factory):
    """
    StoryDetailScreen on the Comments tab with a parent + reply.
    """
    story = _story(
        "story-1",
        "KAN-1",
        title="Review comment thread",
        priority="medium",
    )
    _seed_workspace_list(mock_api, counts={"ws-1": ([story], [])})
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_list_body([story]))
    mock_api.json("GET", "/stories/story-1", body=story)
    mock_api.json(
        "GET",
        "/stories/story-1/comments",
        body=_list_body(
            [
                {
                    "id": "comment-1",
                    "story_id": "story-1",
                    "parent_id": None,
                    "body": "Kicking the tires on this one.",
                    "actor_type": "human",
                    "actor_id": "adam",
                    "created_at": "2026-04-17T10:00:00Z",
                    "updated_at": "2026-04-17T10:00:00Z",
                    "deleted_at": None,
                    "version": 1,
                },
                {
                    "id": "comment-2",
                    "story_id": "story-1",
                    "parent_id": "comment-1",
                    "body": "Looks good to me.",
                    "actor_type": "claude",
                    "actor_id": "outer",
                    "created_at": "2026-04-17T10:30:00Z",
                    "updated_at": "2026-04-17T10:30:00Z",
                    "deleted_at": None,
                    "version": 1,
                },
            ]
        ),
    )
    mock_api.json("GET", "/stories/story-1/linkages", body=_list_body([]))
    mock_api.json("GET", "/audit/entity/story/story-1", body=_list_body([]))

    async def _run(pilot: Any) -> None:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()

    assert snap_compare(app_factory(), run_before=_run, terminal_size=SCREEN_SIZE)


def test_snapshot_story_detail_linkages(snap_compare, mock_api, app_factory):
    """
    StoryDetailScreen on the Linkages tab.
    """
    story = _story("story-1", "KAN-1", title="Source story")
    target = _story("story-2", "KAN-2", title="Target story")
    _seed_workspace_list(mock_api, counts={"ws-1": ([story, target], [])})
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body=_list_body([story, target]),
    )
    mock_api.json("GET", "/stories/story-1", body=story)
    mock_api.json("GET", "/stories/story-1/comments", body=_list_body([]))
    mock_api.json(
        "GET",
        "/stories/story-1/linkages",
        body=_list_body(
            [
                {
                    "id": "link-1",
                    "source_type": "story",
                    "source_id": "story-1",
                    "target_type": "story",
                    "target_id": "story-2",
                    "link_type": "relates_to",
                    "created_at": "2026-04-17T10:00:00Z",
                    "deleted_at": None,
                    "version": 1,
                }
            ]
        ),
    )
    mock_api.json("GET", "/stories/story-2", body=target)
    mock_api.json("GET", "/audit/entity/story/story-1", body=_list_body([]))

    async def _run(pilot: Any) -> None:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause()

    assert snap_compare(app_factory(), run_before=_run, terminal_size=SCREEN_SIZE)


def test_snapshot_story_detail_tags(snap_compare, mock_api, app_factory):
    """
    StoryDetailScreen on the Tags tab.
    """
    story = _story("story-1", "KAN-1", title="Tagged story")
    story["tags"] = [_tag("tag-1", "bug"), _tag("tag-2", "frontend")]
    _seed_workspace_list(mock_api, counts={"ws-1": ([story], [])})
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_list_body([story]))
    mock_api.json("GET", "/stories/story-1", body=story)
    mock_api.json("GET", "/stories/story-1/comments", body=_list_body([]))
    mock_api.json("GET", "/stories/story-1/linkages", body=_list_body([]))
    mock_api.json("GET", "/audit/entity/story/story-1", body=_list_body([]))

    async def _run(pilot: Any) -> None:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("4")
        await pilot.pause()

    assert snap_compare(app_factory(), run_before=_run, terminal_size=SCREEN_SIZE)


def test_snapshot_story_detail_audit(snap_compare, mock_api, app_factory):
    """
    StoryDetailScreen on the Audit tab.
    """
    story = _story("story-1", "KAN-1", title="Audited story")
    _seed_workspace_list(mock_api, counts={"ws-1": ([story], [])})
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_list_body([story]))
    mock_api.json("GET", "/stories/story-1", body=story)
    mock_api.json("GET", "/stories/story-1/comments", body=_list_body([]))
    mock_api.json("GET", "/stories/story-1/linkages", body=_list_body([]))
    mock_api.json(
        "GET",
        "/audit/entity/story/story-1",
        body=_list_body(
            [
                _audit_event(
                    "evt-1",
                    action="created",
                    actor_type="human",
                    actor_id="adam",
                    occurred_at="2026-04-17T09:00:00Z",
                ),
                _audit_event(
                    "evt-2",
                    action="state_changed",
                    actor_type="claude",
                    actor_id="outer",
                    occurred_at="2026-04-17T11:00:00Z",
                    diff={
                        "before": {"state": "backlog"},
                        "after": {"state": "todo"},
                    },
                ),
            ]
        ),
    )

    async def _run(pilot: Any) -> None:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("5")
        await pilot.pause()

    assert snap_compare(app_factory(), run_before=_run, terminal_size=SCREEN_SIZE)


def test_snapshot_epic_list(snap_compare, mock_api, app_factory):
    """
    EpicListScreen with two seeded epics.
    """
    epics = [
        _epic("epic-1", "KAN-E1", title="Kanban phase 1"),
        _epic("epic-2", "KAN-E2", title="Observability polish", state="closed"),
    ]
    _seed_workspace_list(mock_api, counts={"ws-1": ([], epics)})
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_list_body(epics))
    # Story count probes per epic.
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body=_list_body([_story("story-1", "KAN-1", epic_id="epic-1")]),
    )
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_list_body([]))

    async def _run(pilot: Any) -> None:
        await pilot.pause()
        await pilot.press("E")
        await pilot.pause()
        await pilot.pause()

    assert snap_compare(app_factory(), run_before=_run, terminal_size=SCREEN_SIZE)


def test_snapshot_epic_detail(snap_compare, mock_api, app_factory):
    """
    EpicDetailScreen with a couple of stories spread across columns.
    """
    epic = _epic("epic-1", "KAN-E1", title="Kanban phase 1")
    epics = [epic]
    epic_stories = [
        _story(
            "story-1",
            "KAN-1",
            state="todo",
            title="Wire board",
            epic_id="epic-1",
        ),
        _story(
            "story-2",
            "KAN-2",
            state="in_progress",
            title="Add snapshots",
            priority="high",
            epic_id="epic-1",
        ),
    ]
    _seed_workspace_list(mock_api, counts={"ws-1": ([], epics)})
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_list_body(epics))
    # Story count probe.
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_list_body(epic_stories))
    # Epic detail's own scoped fetch.
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_list_body(epic_stories))

    async def _run(pilot: Any) -> None:
        await pilot.pause()
        await pilot.press("E")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

    assert snap_compare(app_factory(), run_before=_run, terminal_size=SCREEN_SIZE)


def test_snapshot_audit_feed(snap_compare, mock_api, app_factory):
    """
    AuditFeedScreen with a handful of seed rows.
    """
    _seed_workspace_list(mock_api)
    mock_api.json(
        "GET",
        "/audit",
        body=_list_body(
            [
                _audit_event(
                    "evt-1",
                    action="created",
                    entity_type="story",
                    entity_id="story-1",
                    actor_type="human",
                    actor_id="adam",
                    occurred_at="2026-04-18T09:00:00Z",
                ),
                _audit_event(
                    "evt-2",
                    action="state_changed",
                    entity_type="story",
                    entity_id="story-1",
                    actor_type="claude",
                    actor_id="outer",
                    occurred_at="2026-04-18T10:00:00Z",
                    diff={
                        "before": {"state": "backlog"},
                        "after": {"state": "todo"},
                    },
                ),
                _audit_event(
                    "evt-3",
                    action="commented",
                    entity_type="story",
                    entity_id="story-1",
                    actor_type="system",
                    actor_id="kb",
                    occurred_at="2026-04-18T11:00:00Z",
                ),
            ]
        ),
    )

    async def _run(pilot: Any) -> None:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await pilot.pause()

    assert snap_compare(app_factory(), run_before=_run, terminal_size=SCREEN_SIZE)


def test_snapshot_search(snap_compare, mock_api, app_factory):
    """
    SearchScreen after the index builds with a few rows.
    """
    stories = [
        _story("story-1", "KAN-1", title="Wire the board"),
        _story("story-2", "KAN-2", title="Ship snapshot tests", priority="high"),
        _story("story-3", "KAN-3", title="Polish the footer"),
    ]
    _seed_workspace_list(mock_api, counts={"ws-1": (stories, [])})
    # Search index rebuild fires /workspaces again plus the per-story
    # stories walk and comment fetches.
    mock_api.json("GET", "/workspaces", body=_list_body([_workspace()]))
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_list_body(stories))
    for story in stories:
        mock_api.json(
            "GET",
            f"/stories/{story['id']}/comments",
            body=_list_body([]),
        )

    async def _run(pilot: Any) -> None:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        await pilot.pause()

    assert snap_compare(app_factory(), run_before=_run, terminal_size=SCREEN_SIZE)


# ---------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------


def test_snapshot_quit_confirm_modal(snap_compare):
    """
    QuitConfirmModal hosted by a minimal app.

    Guards the Rich-markup escape fix: the hint must render as
    ``[Y]es / [N]o`` with literal brackets rather than collapsing to
    ``es / o`` when Rich parses ``[y]``/``[n]`` as markup tags.
    """
    from kanbaroo_tui.screens.workspace_list import QuitConfirmModal

    host = _ModalHost(lambda _host: QuitConfirmModal())
    assert snap_compare(host, terminal_size=MODAL_SIZE)


def test_snapshot_duplicate_confirm_modal(snap_compare):
    """
    DuplicateConfirm hosted by a minimal app.

    Regression guard for the bracket-escape fix: ``[y]es / [n]o`` must
    render literally on the hint row.
    """
    items = [
        _story("story-1", "KAN-1", title="Write snapshot tests"),
        _story("story-2", "KAN-2", title="Write baseline snapshots"),
    ]
    host = _ModalHost(lambda _host: DuplicateConfirm(entity="story", items=items))
    assert snap_compare(host, terminal_size=MODAL_SIZE)


def test_snapshot_tag_picker_modal(snap_compare):
    """
    TagPicker hosted by a minimal app with two workspace tags.
    """
    tags = [_tag("tag-1", "bug"), _tag("tag-2", "frontend")]
    attached = {"tag-1"}
    host = _ModalHost(
        lambda _host: TagPicker(
            client=_modal_host_client(),
            story_id="story-1",
            tags=tags,
            attached_tag_ids=attached,
        )
    )
    assert snap_compare(host, terminal_size=MODAL_SIZE)


def test_snapshot_link_picker_modal(snap_compare):
    """
    LinkPicker hosted by a minimal app, sitting on the empty input
    state before the user types anything.
    """
    source = _story("story-1", "KAN-1", title="Source story")
    host = _ModalHost(
        lambda _host: LinkPicker(
            client=_modal_host_client(),
            source_story=source,
        )
    )
    assert snap_compare(host, terminal_size=MODAL_SIZE)


def test_snapshot_tag_filter_modal(snap_compare):
    """
    TagFilterPicker hosted by a minimal app with two tags.
    """
    tags = [_tag("tag-1", "bug"), _tag("tag-2", "frontend")]
    host = _ModalHost(
        lambda _host: TagFilterPicker(
            tags=tags,
            initial_tag_ids={"tag-1"},
        )
    )
    assert snap_compare(host, terminal_size=MODAL_SIZE)


def test_snapshot_help_modal(snap_compare):
    """
    KeybindingHelp hosted by a minimal app with representative rows.
    """
    bindings = [
        ("j / k", "move cursor"),
        ("enter", "open"),
        ("q", "back"),
        ("?", "this overlay"),
    ]
    host = _ModalHost(lambda _host: KeybindingHelp(title="Sample", bindings=bindings))
    assert snap_compare(host, terminal_size=MODAL_SIZE)
