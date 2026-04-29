"""
Modal overlay for attaching and detaching tags on a story.

The story detail screen pushes this modal when the user presses
``t``. The modal owns the REST calls; the host screen just hands in
the workspace's available tags and the tag ids currently attached,
receives the final attached set on dismiss, and refetches. Running
the HTTP work inside the modal rather than the host screen keeps the
host's code path short and makes the modal self-contained for tests.

Protocol
--------

The modal is parameterized with:

* ``tags``: list of tag dicts from ``GET /workspaces/{id}/tags``.
* ``attached_tag_ids``: ids currently associated with the story.
* ``story_id``: id of the story being edited (used for the REST calls).

On ``enter``, the modal diffs the selection against the initial set:
anything newly selected becomes ``POST /stories/{id}/tags`` with the
new ids; anything unselected becomes a ``DELETE
/stories/{id}/tags/{tag_id}`` per removal. It then dismisses with the
final set of attached tag ids so the host can refresh state. On
``escape`` it dismisses with ``None`` and makes no REST call.
"""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import SelectionList, Static

from kanbaroo_tui.client import ApiError, AsyncApiClient


class TagPicker(ModalScreen[set[str] | None]):
    """
    Modal tag picker for a single story.

    Renders the workspace's tags as a :class:`SelectionList`; space
    toggles, enter confirms, escape aborts. Empty tag lists render a
    hint pointing at ``kb tag create`` so the user knows how to get
    unstuck.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("enter", "confirm", "Confirm", priority=True),
        Binding("j", "cursor_down", "Down", show=False, priority=True),
        Binding("k", "cursor_up", "Up", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    TagPicker {
        align: center middle;
    }
    TagPicker > Vertical {
        width: 60;
        max-width: 80%;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $panel;
        padding: 1 2;
    }
    TagPicker .picker-title {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    TagPicker .picker-hint {
        color: $warning;
        padding: 1 0;
    }
    """

    def __init__(
        self,
        *,
        client: AsyncApiClient,
        story_id: str,
        tags: list[dict[str, Any]],
        attached_tag_ids: set[str],
    ) -> None:
        """
        Build the picker bound to ``story_id`` with the workspace's
        ``tags`` and the currently-attached set.
        """
        super().__init__()
        self._client = client
        self._story_id = story_id
        self._tags = list(tags)
        self._initial = set(attached_tag_ids)

    def compose(self) -> ComposeResult:
        """
        Lay out the centered panel: title, selection list or a hint.
        """
        with Vertical():
            yield Static(
                "Tags (space to toggle, enter to confirm)", classes="picker-title"
            )
            if not self._tags:
                yield Static(
                    "No tags in this workspace. Create one via `kb tag create` first.",
                    classes="picker-hint",
                )
                return
            items = [
                (
                    str(tag.get("name", "")),
                    str(tag.get("id", "")),
                    str(tag.get("id", "")) in self._initial,
                )
                for tag in self._tags
            ]
            yield SelectionList[str](*items, id="tag-picker-list")

    def on_mount(self) -> None:
        """
        Focus the selection list so space/enter work immediately.
        """
        if self._tags:
            picker = self.query_one("#tag-picker-list", SelectionList)
            self.set_focus(picker)

    def action_cancel(self) -> None:
        """
        Dismiss with ``None``; no REST calls are made.
        """
        self.dismiss(None)

    def action_cursor_down(self) -> None:
        """
        Move the selection cursor down. Routes the Vim-style ``j`` key
        through whichever arrow-key action the underlying list exposes.
        """
        if not self._tags:
            return
        picker = self.query_one("#tag-picker-list", SelectionList)
        picker.action_cursor_down()

    def action_cursor_up(self) -> None:
        """
        Move the selection cursor up. Routes the Vim-style ``k`` key
        through whichever arrow-key action the underlying list exposes.
        """
        if not self._tags:
            return
        picker = self.query_one("#tag-picker-list", SelectionList)
        picker.action_cursor_up()

    async def action_confirm(self) -> None:
        """
        Diff the selection against the initial set and issue REST
        calls for each add or remove. Dismisses with the resulting
        set of attached ids on success; a REST failure keeps the
        modal open so the user can retry.
        """
        if not self._tags:
            self.dismiss(set(self._initial))
            return
        picker = self.query_one("#tag-picker-list", SelectionList)
        selected: set[str] = set(str(value) for value in picker.selected)
        to_add = selected - self._initial
        to_remove = self._initial - selected
        try:
            if to_add:
                await self._client.post(
                    f"/stories/{self._story_id}/tags",
                    json={"tag_ids": sorted(to_add)},
                )
            for tag_id in sorted(to_remove):
                await self._client.request(
                    "DELETE",
                    f"/stories/{self._story_id}/tags/{tag_id}",
                )
        except ApiError as exc:
            self.notify(f"tag update failed: {exc}", severity="error")
            return
        self.dismiss(selected)
