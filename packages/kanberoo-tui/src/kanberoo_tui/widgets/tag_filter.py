"""
Modal for picking the active tag filter on the board.

Distinct from :class:`~kanberoo_tui.widgets.tag_picker.TagPicker`,
which mutates a story's tag set via REST calls. This modal is purely
a selector: it returns the chosen set of tag identifiers (name and
id together) to the caller and never touches the network. The board
screen then applies the filter when fetching stories.

The result type is a list of ``(tag_id, tag_name)`` tuples so the
caller can both display the active set in the header line and pass
the names to ``GET /workspaces/{id}/stories?tag=...``.
"""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import SelectionList, Static


class TagFilterPicker(ModalScreen[list[tuple[str, str]] | None]):
    """
    Modal that lets the user pick a set of tag names to filter the
    board by.

    ``tags`` is the workspace's tag list. ``initial_tag_ids`` is the
    currently-active filter (so reopening the modal preserves the
    previous selection). On ``enter`` the modal dismisses with the
    chosen ``[(id, name), ...]`` list (empty list = clear filter).
    On ``escape`` it dismisses with ``None`` so the caller knows to
    leave the existing filter alone.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("enter", "confirm", "Apply", priority=True),
        Binding("j", "cursor_down", "Down", show=False, priority=True),
        Binding("k", "cursor_up", "Up", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    TagFilterPicker {
        align: center middle;
    }
    TagFilterPicker > Vertical {
        width: 60;
        max-width: 80%;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $panel;
        padding: 1 2;
    }
    TagFilterPicker .picker-title {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    TagFilterPicker .picker-hint {
        color: $warning;
        padding: 1 0;
    }
    """

    def __init__(
        self,
        *,
        tags: list[dict[str, Any]],
        initial_tag_ids: set[str],
    ) -> None:
        """
        Build the picker with ``tags`` and ``initial_tag_ids`` already
        ticked.
        """
        super().__init__()
        self._tags = list(tags)
        self._initial = set(initial_tag_ids)

    def compose(self) -> ComposeResult:
        """
        Lay out the centered panel: title, selection list (or hint).
        """
        with Vertical():
            yield Static(
                "Filter by tag (space to toggle, enter to apply)",
                classes="picker-title",
            )
            if not self._tags:
                yield Static(
                    "No tags in this workspace.",
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
            yield SelectionList[str](*items, id="tag-filter-list")

    def on_mount(self) -> None:
        """
        Focus the selection list so space/enter work immediately.
        """
        if self._tags:
            picker = self.query_one("#tag-filter-list", SelectionList)
            self.set_focus(picker)

    def action_cancel(self) -> None:
        """
        Dismiss with ``None``: the caller leaves the filter alone.
        """
        self.dismiss(None)

    def action_cursor_down(self) -> None:
        """
        Move the selection cursor down.
        """
        if not self._tags:
            return
        picker = self.query_one("#tag-filter-list", SelectionList)
        picker.action_cursor_down()

    def action_cursor_up(self) -> None:
        """
        Move the selection cursor up.
        """
        if not self._tags:
            return
        picker = self.query_one("#tag-filter-list", SelectionList)
        picker.action_cursor_up()

    def action_confirm(self) -> None:
        """
        Dismiss with the selected tag identifiers paired with their
        names; an empty list means "clear the filter".
        """
        if not self._tags:
            self.dismiss([])
            return
        picker = self.query_one("#tag-filter-list", SelectionList)
        selected_ids: set[str] = {str(value) for value in picker.selected}
        chosen: list[tuple[str, str]] = [
            (str(tag.get("id", "")), str(tag.get("name", "")))
            for tag in self._tags
            if str(tag.get("id", "")) in selected_ids
        ]
        self.dismiss(chosen)
