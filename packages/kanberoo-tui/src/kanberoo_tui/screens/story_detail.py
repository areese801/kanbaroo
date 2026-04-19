"""
Story detail screen (milestone 13).

Reached from the board view by pressing ``enter`` on a card and from
fuzzy-search results with ``enter``. Renders a single story across
five tabs: description, comments, linkages, tags, audit. Keybindings
cover the mutation surface the detail view needs to be self-contained
without returning to the board or a CLI:

* ``e`` drops into ``$EDITOR`` to edit the description (PATCH on
  save).
* ``c`` drops into ``$EDITOR`` to add a comment (POST when non-empty).
* ``m`` enters move mode with the same ``b/t/p/r/d`` semantics as
  the board.
* ``t`` pushes the tag picker modal.
* ``L`` pushes the link picker modal.
* ``escape`` / ``q`` pop back to the caller.
* ``?`` opens the shared keybinding help overlay.

Live updates
------------

The screen subscribes to the WebSocket fan-out on mount and refetches
on any event touching its story: ``story.*`` for this id, any
``comment.*`` or ``story.commented`` event (comment deletion does not
carry the story id in the envelope, so we refetch unconditionally on
comment events), ``story.tag_*`` for this id, and ``story.linked``/
``story.unlinked`` when the source or target matches.

Audit endpoint fallback
-----------------------

``GET /api/v1/audit/entity/story/{id}`` is reserved for cage K. The
screen calls it anyway and renders a friendly "not yet available"
line on a 404; other errors surface through the normal notification
path.
"""

from __future__ import annotations

from typing import Any, ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    Markdown,
    Static,
    TabbedContent,
    TabPane,
)

from kanberoo_tui.client import ApiError, ApiRequestError
from kanberoo_tui.editor import EditorRunner, edit_markdown
from kanberoo_tui.screens.audit_feed import format_state_transition
from kanberoo_tui.widgets.help_modal import KeybindingHelp
from kanberoo_tui.widgets.link_picker import LinkPicker
from kanberoo_tui.widgets.story_card import actor_badge
from kanberoo_tui.widgets.tag_picker import TagPicker

MOVE_KEY_TO_STATE: dict[str, str] = {
    "b": "backlog",
    "t": "todo",
    "p": "in_progress",
    "r": "in_review",
    "d": "done",
}


class CommentWidget(Static):
    """
    Focusable :class:`Static` wrapping one comment body.

    The screen-level ``R`` binding needs to know which comment the
    cursor is on so it can post a reply against the right
    ``parent_id``; making the widget focusable is cheaper than
    maintaining a parallel cursor index. ``comment`` is the raw REST
    body for the wrapped comment (the screen reads ``id`` and
    ``parent_id`` off it).
    """

    can_focus = True

    def __init__(
        self,
        comment: dict[str, Any],
        markup: str,
        *,
        classes: str | None = None,
    ) -> None:
        """
        Build a focusable comment bubble around ``comment`` with
        ``markup`` as the pre-rendered body.
        """
        super().__init__(markup, classes=classes)
        self._comment = comment

    @property
    def comment(self) -> dict[str, Any]:
        """
        Return the underlying comment dict.
        """
        return self._comment


TAB_IDS: list[str] = [
    "tab-description",
    "tab-comments",
    "tab-linkages",
    "tab-tags",
    "tab-audit",
]

HELP_ROWS: list[tuple[str, str]] = [
    ("e", "edit description in $EDITOR"),
    ("c", "add comment in $EDITOR"),
    ("R", "reply to focused comment (Comments tab)"),
    ("m then b/t/p/r/d", "move the story to a new state"),
    ("t", "toggle tags"),
    ("L", "link to another story"),
    ("1-5", "jump to tab by index"),
    ("[ / ]", "previous / next tab"),
    ("tab / shift+tab", "previous / next tab"),
    ("r", "refresh"),
    ("esc / q", "back"),
    ("?", "this overlay"),
]

STATE_BADGE_STYLES: dict[str, str] = {
    "backlog": "dim",
    "todo": "bold blue",
    "in_progress": "bold yellow",
    "in_review": "bold magenta",
    "done": "bold green",
}

PRIORITY_STYLES: dict[str, str] = {
    "none": "dim",
    "low": "bold #7faa3a",
    "medium": "bold yellow",
    "high": "bold red",
}

ACTOR_STYLES: dict[str, str] = {
    "human": "bold",
    "claude": "bold magenta",
    "system": "dim",
}


def _escape_markup(text: str) -> str:
    """
    Escape Textual markup characters so user text does not open a tag.
    """
    return text.replace("[", "\\[")


class StoryDetailScreen(Screen[None]):
    """
    Full-page detail view for a single story.

    ``story`` is the REST body passed in by the caller. The screen
    refetches on mount so subsequent navigation back into it picks up
    any mutations we missed while it was not mounted.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("e", "edit_description", "Edit"),
        Binding("c", "add_comment", "Comment"),
        Binding("R", "reply_to_comment", "Reply"),
        Binding("m", "enter_move_mode", "Move"),
        Binding("t", "toggle_tags", "Tags"),
        Binding("L", "open_link_picker", "Link"),
        Binding("r", "refresh_story", "Refresh"),
        Binding("1", "tab_index(0)", "Desc", show=False, priority=True),
        Binding("2", "tab_index(1)", "Comments", show=False, priority=True),
        Binding("3", "tab_index(2)", "Links", show=False, priority=True),
        Binding("4", "tab_index(3)", "Tags", show=False, priority=True),
        Binding("5", "tab_index(4)", "Audit", show=False, priority=True),
        Binding("]", "tab_next", "Next tab", show=False, priority=True),
        Binding("[", "tab_prev", "Prev tab", show=False, priority=True),
        Binding("tab", "tab_next", "Next tab", show=False, priority=True),
        Binding("shift+tab", "tab_prev", "Prev tab", show=False, priority=True),
        Binding("?", "show_help", "Help", show=False),
        Binding("q", "back", "Back"),
        Binding("escape", "back", "Back", show=False),
    ]

    DEFAULT_CSS = """
    StoryDetailScreen {
        layout: vertical;
    }
    StoryDetailScreen .story-header {
        padding: 1 2;
        border: round $panel-lighten-1;
    }
    StoryDetailScreen .story-chips {
        padding: 0 2;
        color: $text-muted;
    }
    StoryDetailScreen TabbedContent {
        height: 1fr;
    }
    StoryDetailScreen Markdown {
        padding: 1 2;
    }
    StoryDetailScreen .empty-hint {
        padding: 1 2;
        color: $warning;
    }
    StoryDetailScreen .comment {
        padding: 1 2;
        border-bottom: solid $panel;
    }
    StoryDetailScreen .comment-reply {
        padding: 1 4;
        border-bottom: solid $panel-lighten-1;
    }
    """

    def __init__(
        self,
        story: dict[str, Any],
        *,
        editor_runner: EditorRunner | None = None,
    ) -> None:
        """
        Build a detail screen for ``story``. ``editor_runner`` is
        forwarded to :func:`edit_markdown` so tests can inject a fake
        editor; production callers leave it ``None`` so the default
        suspend-and-launch-``$EDITOR`` flow runs.
        """
        super().__init__()
        self._story: dict[str, Any] = dict(story)
        self._comments: list[dict[str, Any]] = []
        self._linkages: list[dict[str, Any]] = []
        self._tags: list[dict[str, Any]] = []
        self._audit: list[dict[str, Any]] | None = None
        self._audit_unavailable: bool = False
        self._move_mode: bool = False
        self._editor_runner = editor_runner

    @property
    def story(self) -> dict[str, Any]:
        """
        Return the latest-known story body. Exposed for tests.
        """
        return dict(self._story)

    @property
    def current_workspace_id(self) -> str | None:
        """
        Return the id of the workspace owning this story, if known.

        The story detail screen only carries the story body, not the
        workspace dict. The app's global ``E`` binding calls this to
        look up the workspace via REST when the stack otherwise has no
        workspace context.
        """
        ws_id = self._story.get("workspace_id")
        if not ws_id:
            return None
        return str(ws_id)

    @property
    def move_mode(self) -> bool:
        """
        Return whether move mode is currently armed. Exposed for tests.
        """
        return self._move_mode

    def compose(self) -> ComposeResult:
        """
        Lay out the persistent chrome plus the tabs.

        Each :class:`TabPane` owns one populated body widget; the
        screen updates those widgets in place on refresh rather than
        rebuilding the tab structure.
        """
        yield Header()
        yield Static(id="story-header", classes="story-header")
        yield Static(id="story-chips", classes="story-chips")
        with TabbedContent(id="story-tabs"):
            with TabPane("1 Description", id="tab-description"):
                yield Markdown(id="story-description")
            with TabPane("2 Comments", id="tab-comments"):
                yield VerticalScroll(id="comments-body")
            with TabPane("3 Linkages", id="tab-linkages"):
                yield VerticalScroll(id="linkages-body")
            with TabPane("4 Tags", id="tab-tags"):
                yield Static(id="tags-body")
            with TabPane("5 Audit", id="tab-audit"):
                yield VerticalScroll(id="audit-body")
        yield Footer()

    async def on_mount(self) -> None:
        """
        Register for WS events and populate every tab body.
        """
        human_id = str(self._story.get("human_id", ""))
        key = human_id.split("-", 1)[0] if "-" in human_id else ""
        if key and human_id:
            self.sub_title = f"{key} - {human_id}"
        else:
            self.sub_title = human_id or "Story"
        self.app.register_ws_listener(self)  # type: ignore[attr-defined]
        await self.refresh_data()

    def on_unmount(self) -> None:
        """
        Deregister the WS listener so re-entering the screen registers
        fresh state.
        """
        self.app.unregister_ws_listener(self)  # type: ignore[attr-defined]

    async def refresh_data(self) -> None:
        """
        Refetch the story and every tab payload.

        Network failures surface as a notification; per-tab rendering
        handles empty or absent data on its own so one slow endpoint
        does not blank the whole screen.
        """
        client = self.app.client  # type: ignore[attr-defined]
        story_id = str(self._story.get("id", ""))
        try:
            story_response = await client.get(f"/stories/{story_id}")
        except ApiError as exc:
            self.notify(f"story fetch failed: {exc}", severity="error")
            return
        self._story = dict(story_response.json())
        try:
            comments_response = await client.get(f"/stories/{story_id}/comments")
            self._comments = list(comments_response.json().get("items", []))
        except ApiError as exc:
            self.notify(f"comments fetch failed: {exc}", severity="error")
            self._comments = []
        try:
            linkages_response = await client.get(f"/stories/{story_id}/linkages")
            self._linkages = list(linkages_response.json().get("items", []))
        except ApiError as exc:
            self.notify(f"linkages fetch failed: {exc}", severity="error")
            self._linkages = []
        self._tags = self._extract_embedded_tags()
        await self._fetch_audit(client, story_id)
        self._render_header()
        self._render_description()
        await self._render_comments()
        await self._render_linkages()
        self._render_tags()
        await self._render_audit()

    def _extract_embedded_tags(self) -> list[dict[str, Any]]:
        """
        Return tags attached to the story when the response embeds
        them.

        Spec section 4.2 says ``GET /stories/{id}`` includes tags, but
        the current ``StoryRead`` schema does not carry a ``tags``
        field in every environment; a future milestone (cage K or
        later) will make this mandatory. Until then we look for an
        embedded ``tags`` list and fall back to empty, which keeps the
        picker usable (attaches still work) without claiming the
        detached set is known.
        """
        embedded = self._story.get("tags")
        if isinstance(embedded, list):
            return [t for t in embedded if isinstance(t, dict)]
        return []

    async def _fetch_audit(self, client: Any, story_id: str) -> None:
        """
        Call the per-entity audit endpoint.

        A 404 is expected today (cage K owns audit). We stash an
        ``_audit_unavailable`` flag so the tab can render a friendly
        message rather than a blank area. Other errors propagate into
        the notification system.
        """
        try:
            response = await client.get(f"/audit/entity/story/{story_id}")
        except ApiRequestError as exc:
            if exc.status_code == 404:
                self._audit = []
                self._audit_unavailable = True
                return
            self.notify(f"audit fetch failed: {exc}", severity="error")
            self._audit = []
            return
        except ApiError as exc:
            self.notify(f"audit fetch failed: {exc}", severity="error")
            self._audit = []
            return
        body = response.json()
        if isinstance(body, dict):
            self._audit = list(body.get("items", []))
        elif isinstance(body, list):
            self._audit = list(body)
        else:
            self._audit = []
        self._audit_unavailable = False

    def _render_header(self) -> None:
        """
        Render the two header rows: title/state/priority and chip row
        for epic, branch, commit, PR, state actor.
        """
        human_id = _escape_markup(str(self._story.get("human_id", "?")))
        title = _escape_markup(str(self._story.get("title", "")))
        state = str(self._story.get("state", ""))
        state_style = STATE_BADGE_STYLES.get(state, "bold")
        priority = str(self._story.get("priority", "none"))
        priority_style = PRIORITY_STYLES.get(priority, "dim")
        actor_type = self._story.get("state_actor_type")
        actor_bit = ""
        if actor_type:
            actor_style = ACTOR_STYLES.get(str(actor_type), "bold")
            badge = _escape_markup(actor_badge(str(actor_type)))
            actor_bit = f"  [{actor_style}]{badge}[/{actor_style}]"
        header_markup = (
            f"[bold]{human_id}[/bold]  {title}\n"
            f"[{state_style}]\\[{state}][/{state_style}]  "
            f"[{priority_style}]\\[{priority}][/{priority_style}]"
            f"{actor_bit}"
        )
        self.query_one("#story-header", Static).update(header_markup)
        chips: list[str] = []
        epic_id = self._story.get("epic_id")
        if epic_id:
            chips.append(f"epic:{_escape_markup(str(epic_id))}")
        branch = self._story.get("branch_name")
        if branch:
            chips.append(f"branch:{_escape_markup(str(branch))}")
        commit = self._story.get("commit_sha")
        if commit:
            chips.append(f"commit:{_escape_markup(str(commit))[:12]}")
        pr = self._story.get("pr_url")
        if pr:
            chips.append(f"pr:{_escape_markup(str(pr))}")
        chip_row = "  ".join(chips) if chips else "(no linked branch/commit/PR)"
        self.query_one("#story-chips", Static).update(chip_row)

    def _render_description(self) -> None:
        """
        Push the markdown description into the description tab.
        """
        markdown = self.query_one("#story-description", Markdown)
        body = self._story.get("description") or "*(no description)*"
        markdown.update(body)

    async def _render_comments(self) -> None:
        """
        Rebuild the comments tab.

        Comments render newest-last per the spec and indent replies
        once; the server enforces one-level threading, so we never
        need deeper nesting. Each comment is wrapped in a focusable
        :class:`CommentWidget` so the ``R`` binding can tell which
        comment the user is replying to.
        """
        body = self.query_one("#comments-body", VerticalScroll)
        for child in list(body.children):
            await child.remove()
        if not self._comments:
            await body.mount(Static("(no comments yet)", classes="empty-hint"))
            return
        parents: list[dict[str, Any]] = [
            c for c in self._comments if not c.get("parent_id")
        ]
        replies_by_parent: dict[str, list[dict[str, Any]]] = {}
        for comment in self._comments:
            parent_id = comment.get("parent_id")
            if parent_id:
                replies_by_parent.setdefault(str(parent_id), []).append(comment)
        for comment in parents:
            await body.mount(
                CommentWidget(
                    comment,
                    _format_comment(comment),
                    classes="comment",
                )
            )
            for reply in replies_by_parent.get(str(comment.get("id", "")), []):
                await body.mount(
                    CommentWidget(
                        reply,
                        _format_comment(reply, is_reply=True),
                        classes="comment-reply",
                    )
                )

    async def _render_linkages(self) -> None:
        """
        Rebuild the linkages tab.

        Cage E's service returns a merged list (incoming + outgoing).
        We split by direction (comparing source_id to this story's id)
        and group within each direction by link_type. The endpoint
        already deduplicates the mirror pair for blocks/duplicates, so
        each pair appears exactly once.

        Each linkage resolves its far end (story or epic, based on
        ``target_type``/``source_type``) into a ``human_id "title"``
        label so the tab is legible. That is one extra GET per
        linkage row; at single-user scale the amortised cost is
        negligible. If the linkage count grows enough that render
        time shows up in a profile, batch the fetches by
        ``(type, id)``.
        """
        body = self.query_one("#linkages-body", VerticalScroll)
        for child in list(body.children):
            await child.remove()
        if not self._linkages:
            await body.mount(Static("(no linkages)", classes="empty-hint"))
            return
        story_id = str(self._story.get("id", ""))
        outgoing: dict[str, list[dict[str, Any]]] = {}
        incoming: dict[str, list[dict[str, Any]]] = {}
        for linkage in self._linkages:
            bucket = (
                outgoing if str(linkage.get("source_id", "")) == story_id else incoming
            )
            bucket.setdefault(str(linkage.get("link_type", "")), []).append(linkage)
        if outgoing:
            await body.mount(Static("[bold]outgoing[/bold]"))
            for link_type, rows in sorted(outgoing.items()):
                await body.mount(Static(f"  {_escape_markup(link_type)}:"))
                for row in rows:
                    label = await self._linkage_label(
                        str(row.get("target_type", "story")),
                        str(row.get("target_id", "")),
                    )
                    await body.mount(Static(f"    \u2192 {label}"))
        if incoming:
            await body.mount(Static("[bold]incoming[/bold]"))
            for link_type, rows in sorted(incoming.items()):
                await body.mount(Static(f"  {_escape_markup(link_type)}:"))
                for row in rows:
                    label = await self._linkage_label(
                        str(row.get("source_type", "story")),
                        str(row.get("source_id", "")),
                    )
                    await body.mount(Static(f"    \u2190 {label}"))

    async def _linkage_label(self, entity_type: str, entity_id: str) -> str:
        """
        Return ``{human_id} "{title}"`` for the linkage endpoint, or
        the raw UUID with a ``(not accessible)`` suffix when the fetch
        fails (deleted, 404, transport error).

        ``entity_type`` is ``story`` or ``epic`` and picks the REST
        path segment. Anything else falls back to the story path so
        an unexpected value never breaks the render.
        """
        if not entity_id:
            return ""
        segment = "epics" if entity_type == "epic" else "stories"
        try:
            response = await self.app.client.get(  # type: ignore[attr-defined]
                f"/{segment}/{entity_id}"
            )
        except ApiError:
            return f"{_escape_markup(entity_id)} (not accessible)"
        body = response.json()
        human_id = _escape_markup(str(body.get("human_id", "")))
        title = _escape_markup(str(body.get("title", "")))
        if human_id and title:
            return f'{human_id} "{title}"'
        if human_id:
            return human_id
        return _escape_markup(entity_id)

    def _render_tags(self) -> None:
        """
        Rebuild the tags tab as an inline chip list.
        """
        tags_body = self.query_one("#tags-body", Static)
        if not self._tags:
            tags_body.update("(no tags)")
            return
        chips: list[str] = []
        for tag in self._tags:
            name = _escape_markup(str(tag.get("name", "")))
            chips.append(f"[cyan]#{name}[/cyan]")
        tags_body.update(" ".join(chips))

    async def _render_audit(self) -> None:
        """
        Rebuild the audit tab with the per-entity timeline.
        """
        body = self.query_one("#audit-body", VerticalScroll)
        for child in list(body.children):
            await child.remove()
        if self._audit_unavailable:
            await body.mount(
                Static(
                    "audit endpoint not yet available (cage K).",
                    classes="empty-hint",
                )
            )
            return
        if not self._audit:
            await body.mount(Static("(no audit events)", classes="empty-hint"))
            return
        for event in self._audit:
            when = _escape_markup(str(event.get("occurred_at", "")))
            actor_type = str(event.get("actor_type", "?"))
            badge = _escape_markup(actor_badge(actor_type))
            actor_id = _escape_markup(str(event.get("actor_id", "?")))
            action = _escape_markup(str(event.get("action", "")))
            transition = format_state_transition(event)
            if transition is not None:
                action = f"{action}  [bold]{_escape_markup(transition)}[/bold]"
            await body.mount(Static(f"{when}  {badge} {actor_id}  {action}"))

    async def action_show_help(self) -> None:
        """
        Push the shared help overlay with this screen's bindings.
        """
        await self.app.push_screen(
            KeybindingHelp(title="Story detail", bindings=HELP_ROWS)
        )

    def action_tab_index(self, index: int) -> None:
        """
        Activate the tab at ``index`` (0-based).

        Out-of-range indices are silently ignored so a keypress never
        raises when the tab list changes.
        """
        if index < 0 or index >= len(TAB_IDS):
            return
        tabs = self.query_one("#story-tabs", TabbedContent)
        tabs.active = TAB_IDS[index]

    def action_tab_next(self) -> None:
        """
        Activate the tab after the currently active one, wrapping.
        """
        tabs = self.query_one("#story-tabs", TabbedContent)
        try:
            current = TAB_IDS.index(tabs.active)
        except ValueError:
            current = 0
        tabs.active = TAB_IDS[(current + 1) % len(TAB_IDS)]

    def action_tab_prev(self) -> None:
        """
        Activate the tab before the currently active one, wrapping.
        """
        tabs = self.query_one("#story-tabs", TabbedContent)
        try:
            current = TAB_IDS.index(tabs.active)
        except ValueError:
            current = 0
        tabs.active = TAB_IDS[(current - 1) % len(TAB_IDS)]

    def action_back(self) -> None:
        """
        Pop back to the caller.
        """
        self.app.pop_screen()

    async def action_refresh_story(self) -> None:
        """
        Keybinding handler for ``r``.
        """
        await self.refresh_data()
        self.notify("story refreshed")

    async def action_edit_description(self) -> None:
        """
        Launch ``$EDITOR`` on the current description and PATCH the
        story when the buffer changes.
        """
        current = self._story.get("description") or ""
        edited = await edit_markdown(self.app, current, runner=self._editor_runner)
        if edited is None:
            self.notify("no changes")
            return
        client = self.app.client  # type: ignore[attr-defined]
        story_id = str(self._story.get("id", ""))
        version = int(self._story.get("version", 1))
        try:
            response = await client.request(
                "PATCH",
                f"/stories/{story_id}",
                json={"description": edited},
                headers={"If-Match": str(version)},
            )
        except ApiError as exc:
            self.notify(f"update failed: {exc}", severity="error")
            return
        self._story = dict(response.json())
        self._render_header()
        self._render_description()
        self.notify("description updated")

    async def action_add_comment(self) -> None:
        """
        Launch ``$EDITOR`` on an empty buffer and POST a comment when
        the buffer is non-empty.
        """
        edited = await edit_markdown(self.app, "", runner=self._editor_runner)
        if edited is None or not edited.strip():
            self.notify("comment aborted")
            return
        client = self.app.client  # type: ignore[attr-defined]
        story_id = str(self._story.get("id", ""))
        try:
            await client.post(
                f"/stories/{story_id}/comments",
                json={"body": edited},
            )
        except ApiError as exc:
            self.notify(f"comment failed: {exc}", severity="error")
            return
        self.notify("comment posted")
        await self.refresh_data()

    async def action_reply_to_comment(self) -> None:
        """
        Reply to the focused comment on the Comments tab.

        Walks the focused-widget ancestry to find the enclosing
        :class:`CommentWidget` so the action fires against whichever
        comment currently has focus. A reply to a reply is rejected
        per spec section 3.1 (one-level threading); no comment in
        focus flashes a hint and skips the editor round-trip. On
        success the screen refetches so the new reply appears without
        waiting for the ``story.commented`` WS event.
        """
        comment_widget = self._focused_comment_widget()
        if comment_widget is None:
            self.notify("focus a comment to reply", severity="warning")
            return
        comment = comment_widget.comment
        if comment.get("parent_id"):
            self.notify("cannot reply to a reply", severity="warning")
            return
        edited = await edit_markdown(self.app, "", runner=self._editor_runner)
        if edited is None or not edited.strip():
            self.notify("reply aborted")
            return
        client = self.app.client  # type: ignore[attr-defined]
        story_id = str(self._story.get("id", ""))
        parent_id = str(comment.get("id", ""))
        try:
            await client.post(
                f"/stories/{story_id}/comments",
                json={"body": edited, "parent_id": parent_id},
            )
        except ApiError as exc:
            self.notify(f"reply failed: {exc}", severity="error")
            return
        self.notify("reply posted")
        await self.refresh_data()

    def _focused_comment_widget(self) -> CommentWidget | None:
        """
        Return the :class:`CommentWidget` the focus currently sits on
        (or inside), or ``None`` if nothing comment-shaped has focus.
        """
        node: Any | None = self.focused
        while node is not None:
            if isinstance(node, CommentWidget):
                return node
            node = getattr(node, "parent", None)
        return None

    def action_enter_move_mode(self) -> None:
        """
        Enter move mode; next key picks a target state.
        """
        self._move_mode = True
        self.notify("move: b/t/p/r/d, esc to cancel")

    async def action_toggle_tags(self) -> None:
        """
        Open the tag picker modal.
        """
        client = self.app.client  # type: ignore[attr-defined]
        workspace_id = str(self._story.get("workspace_id", ""))
        try:
            response = await client.get(f"/workspaces/{workspace_id}/tags")
        except ApiError as exc:
            self.notify(f"tag fetch failed: {exc}", severity="error")
            return
        workspace_tags = list(response.json().get("items", []))
        attached_ids = {str(tag.get("id", "")) for tag in self._tags}
        picker = TagPicker(
            client=client,
            story_id=str(self._story.get("id", "")),
            tags=workspace_tags,
            attached_tag_ids=attached_ids,
        )

        async def _on_dismiss(result: set[str] | None) -> None:
            if result is None:
                return
            await self.refresh_data()

        await self.app.push_screen(picker, _on_dismiss)

    async def action_open_link_picker(self) -> None:
        """
        Open the link picker modal.
        """
        client = self.app.client  # type: ignore[attr-defined]
        picker = LinkPicker(client=client, source_story=self._story)

        async def _on_dismiss(result: dict[str, Any] | None) -> None:
            if result is None:
                return
            await self.refresh_data()
            self.notify(f"linked -> {result.get('target_id', '?')}")

        await self.app.push_screen(picker, _on_dismiss)

    async def on_key(self, event: events.Key) -> None:
        """
        Consume the next key while move mode is armed.
        """
        if not self._move_mode:
            return
        if event.key == "escape":
            self._move_mode = False
            self.notify("move cancelled")
            event.stop()
            return
        target = MOVE_KEY_TO_STATE.get(event.key)
        self._move_mode = False
        event.stop()
        if target is None:
            self.notify(f"unknown move target: {event.key}")
            return
        await self._transition(target)

    async def _transition(self, to_state: str) -> None:
        """
        POST the transition with ``If-Match`` from the current story.
        """
        current_state = str(self._story.get("state", ""))
        if current_state == to_state:
            self.notify(f"already in {to_state}")
            return
        client = self.app.client  # type: ignore[attr-defined]
        story_id = str(self._story.get("id", ""))
        try:
            await client.post_with_etag(
                f"/stories/{story_id}",
                f"/stories/{story_id}/transition",
                json={"to_state": to_state},
            )
        except ApiError as exc:
            self.notify(f"transition failed: {exc}", severity="error")
            return
        self.notify(f"moved to {to_state}")
        await self.refresh_data()

    async def handle_ws_event(self, event: dict[str, Any]) -> None:
        """
        Refetch on any event that touches this story.

        Comment and linkage deletions do not always carry enough in
        the envelope to filter precisely; the cost of a redundant
        refetch is low, so we err on the side of refetching whenever
        the event type is plausibly related.
        """
        event_type = str(event.get("event_type", ""))
        entity_type = str(event.get("entity_type", ""))
        entity_id = str(event.get("entity_id", ""))
        this_id = str(self._story.get("id", ""))
        payload = event.get("payload") or {}
        if entity_type == "story" and entity_id == this_id:
            await self.refresh_data()
            return
        if event_type in {
            "story.commented",
            "story.tag_added",
            "story.tag_removed",
            "story.linked",
            "story.unlinked",
        } and (
            entity_id == this_id
            or (isinstance(payload, dict) and payload.get("story_id") == this_id)
            or (isinstance(payload, dict) and payload.get("source_id") == this_id)
            or (isinstance(payload, dict) and payload.get("target_id") == this_id)
        ):
            await self.refresh_data()
            return
        if event_type in {"comment.updated", "comment.deleted"} and (
            isinstance(payload, dict) and payload.get("story_id") == this_id
        ):
            await self.refresh_data()


def _format_comment(comment: dict[str, Any], *, is_reply: bool = False) -> str:
    """
    Format a single comment for display in the comments tab.

    Lays the actor chip and timestamp over the body. Replies render
    with a leading arrow so the indentation class does not have to
    carry the visual cue on its own.
    """
    actor_type = str(comment.get("actor_type", "?"))
    actor_id = str(comment.get("actor_id", "?"))
    style = ACTOR_STYLES.get(actor_type, "bold")
    badge = _escape_markup(actor_badge(actor_type))
    when = _escape_markup(str(comment.get("created_at", "")))
    body = _escape_markup(str(comment.get("body", "")))
    prefix = "\u21aa " if is_reply else ""
    return (
        f"{prefix}[{style}]{badge} {_escape_markup(actor_id)}"
        f"[/{style}]  [dim]{when}[/dim]\n{body}"
    )
