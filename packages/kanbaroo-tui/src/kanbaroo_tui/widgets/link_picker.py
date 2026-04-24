"""
Modal overlay for creating a typed linkage between two stories.

Pressed from story detail with ``L``. Scope for v1 is intentionally
small: the user types a target human id (``KAN-7``) and picks a link
type from a fixed list; no autocomplete, no workspace hopping UI. The
modal owns the two REST calls (resolve the target by human id and
POST /linkages) so the host screen's path stays short.

Dismissal contract
------------------

On ``enter`` the modal issues the REST calls and, on success,
dismisses with the new linkage body so the host can update state
without a refetch round-trip (the host refetches anyway on the
WS-delivered ``story.linked`` event, but returning the body keeps the
modal reusable for callers that prefer optimism). On ``escape`` it
dismisses with ``None``. REST failures keep the modal open with a
notification so the user can retry.
"""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from kanbaroo_tui.client import ApiError, AsyncApiClient

LINK_TYPES: list[str] = [
    "relates_to",
    "blocks",
    "is_blocked_by",
    "duplicates",
    "is_duplicated_by",
]


class LinkPicker(ModalScreen[dict[str, Any] | None]):
    """
    Modal link picker for a single source story.

    ``source_story`` is the full story dict of the originating side.
    The user fills the input with a target's ``KAN-N`` human id and
    selects one of the :data:`LINK_TYPES`; ``enter`` submits.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+s", "submit", "Submit"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    DEFAULT_CSS = """
    LinkPicker {
        align: center middle;
    }
    LinkPicker > Vertical {
        width: 60;
        max-width: 80%;
        height: auto;
        border: round $accent;
        background: $panel;
        padding: 1 2;
    }
    LinkPicker .picker-title {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    LinkPicker Input {
        margin-bottom: 1;
    }
    LinkPicker OptionList {
        height: auto;
        max-height: 10;
    }
    """

    def __init__(
        self,
        *,
        client: AsyncApiClient,
        source_story: dict[str, Any],
    ) -> None:
        """
        Build the picker bound to ``source_story``.
        """
        super().__init__()
        self._client = client
        self._source_story = source_story
        self._resolved_target: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        """
        Lay out the centered panel: title, target input, resolved-
        target preview, link-type options, hint footer.
        """
        with Vertical():
            yield Static(
                f"Link {self._source_story.get('human_id', '?')} to ...",
                classes="picker-title",
            )
            yield Input(placeholder="target human id (e.g. KAN-7)", id="link-target")
            yield Static("", id="link-target-resolved", classes="picker-hint")
            option_list: OptionList = OptionList(
                *[Option(link, id=link) for link in LINK_TYPES],
                id="link-type",
            )
            yield option_list
            yield Static(
                "enter resolves target, ctrl+s submits, esc cancels",
                classes="picker-title",
            )

    def on_mount(self) -> None:
        """
        Focus the input so the user can type immediately.
        """
        self.query_one("#link-target", Input).focus()

    def action_cancel(self) -> None:
        """
        Dismiss without making a REST call.
        """
        self.dismiss(None)

    def action_cursor_down(self) -> None:
        """
        Move the link-type option list cursor down.

        Non-priority so the typing path in the target Input is not
        shadowed; fires only when focus is on the OptionList (or
        another non-Input widget within the modal).
        """
        option_list = self.query_one("#link-type", OptionList)
        option_list.action_cursor_down()

    def action_cursor_up(self) -> None:
        """
        Move the link-type option list cursor up.

        Non-priority for the same reason as :meth:`action_cursor_down`.
        """
        option_list = self.query_one("#link-type", OptionList)
        option_list.action_cursor_up()

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        """
        Resolve the human id into a story body when the user hits
        enter in the input, and display the resolved title below so
        the user can sanity-check before ``ctrl+s``.

        A successful lookup caches ``_resolved_target`` so
        :meth:`action_submit` can POST without re-resolving; a miss
        clears the cache and shows ``not found`` so the user knows
        to correct their input. The user should never be able to
        POST a bogus linkage because submit checks the cache before
        firing.
        """
        if message.input.id != "link-target":
            return
        ref = message.value.strip()
        preview = self.query_one("#link-target-resolved", Static)
        if not ref:
            self._resolved_target = None
            preview.update("")
            return
        try:
            target = await self._resolve_target(ref)
        except ApiError:
            self._resolved_target = None
            preview.update(f"[red]not found: {ref}[/red]")
            return
        self._resolved_target = target
        human_id = str(target.get("human_id", ""))
        title = str(target.get("title", ""))
        escaped_title = title.replace("[", "\\[")
        preview.update(f"[green]\u2192 {human_id}[/green] {escaped_title}")

    async def action_submit(self) -> None:
        """
        POST the linkage using the previously-resolved target.

        The resolve step runs on :meth:`on_input_submitted` so the
        user can sanity-check the target title before committing; if
        nothing is cached yet we nudge the user to press enter in the
        input first rather than silently looking up on submit.
        """
        option_list = self.query_one("#link-type", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            self.notify("pick a link type with the arrow keys", severity="warning")
            return
        if self._resolved_target is None:
            target_input = self.query_one("#link-target", Input)
            ref = target_input.value.strip()
            if not ref:
                self.notify("type a target human id first", severity="warning")
                return
            self.notify(
                "press enter in the input to resolve the target first",
                severity="warning",
            )
            return
        option = option_list.get_option_at_index(highlighted)
        link_type = str(option.id)
        try:
            response = await self._client.post(
                "/linkages",
                json={
                    "source_type": "story",
                    "source_id": str(self._source_story.get("id", "")),
                    "target_type": "story",
                    "target_id": str(self._resolved_target.get("id", "")),
                    "link_type": link_type,
                },
            )
        except ApiError as exc:
            self.notify(f"link failed: {exc}", severity="error")
            return
        self.dismiss(response.json())

    async def _resolve_target(self, ref: str) -> dict[str, Any]:
        """
        Translate ``ref`` (``KAN-N`` or a UUID) into a story body.

        The ``by-key`` endpoint accepts the human id directly. A UUID
        ref skips the indirection and hits ``/stories/{id}``.
        """
        if "-" in ref and not ref.startswith("00"):
            response = await self._client.get(f"/stories/by-key/{ref}")
        else:
            response = await self._client.get(f"/stories/{ref}")
        return dict(response.json())
