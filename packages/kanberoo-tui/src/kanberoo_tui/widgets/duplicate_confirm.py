"""
Modal confirming whether to create an entity with a duplicate-looking
title.

Used by the board screen's ``n`` (new story) action: after fetching
the proposed title's similar matches the screen pushes this modal so
the user can decide whether to proceed or cancel. The modal owns no
REST calls; it is purely a yes/no surface that returns ``True`` to
proceed and ``False`` (or ``None``) to cancel.
"""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


def _escape_markup(value: str) -> str:
    """
    Escape ``[`` in ``value`` so Rich renders brackets literally.

    Static widgets feed their text through Rich's markup parser, which
    means user-provided titles like ``[WIP] rewrite`` disappear as
    unknown tags. Prefixing every ``[`` with a backslash tells Rich to
    treat the token as literal text.
    """
    return value.replace("[", "\\[")


class DuplicateConfirm(ModalScreen[bool | None]):
    """
    Modal that warns the user about likely duplicates and prompts
    for a yes/no decision.

    ``y`` confirms (returns ``True``); ``n`` and ``escape`` cancel
    (return ``False``). The modal is intentionally tiny: no list
    cursor, no pagination, just a short list of matches.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "confirm", "Yes create", priority=True),
        Binding("n", "cancel", "No cancel", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    DEFAULT_CSS = """
    DuplicateConfirm {
        align: center middle;
    }
    DuplicateConfirm > Vertical {
        width: 60;
        max-width: 80%;
        height: auto;
        max-height: 80%;
        border: round $warning;
        background: $panel;
        padding: 1 2;
    }
    DuplicateConfirm .dup-title {
        text-style: bold;
        color: $warning;
        padding-bottom: 1;
    }
    DuplicateConfirm .dup-prompt {
        padding-top: 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        *,
        entity: str,
        items: list[dict[str, Any]],
        label_key: str = "human_id",
    ) -> None:
        """
        Build a modal listing ``items`` for ``entity`` (``story``,
        ``epic``, ``tag``).

        ``label_key`` selects which field is rendered first on each
        row. Stories and epics use ``human_id``; tags would use
        ``name``. The modal does not paginate; callers should keep
        ``items`` short.
        """
        super().__init__()
        self._entity = entity
        self._items = list(items)
        self._label_key = label_key

    def compose(self) -> ComposeResult:
        """
        Lay out the centered panel: warning header, match list,
        prompt line.

        The hint escapes its square brackets for Rich markup (``\\[``)
        so ``[y]es / [n]o`` renders literally instead of Rich swallowing
        ``[y]`` and ``[n]`` as unknown tags and leaving ``es / o`` on
        screen (matches the fix applied to ``QuitConfirmModal``).

        Title and labels from arbitrary user data are routed through
        :func:`_escape_markup` so a story titled ``[WIP] whatever``
        renders literally rather than as a Rich tag.
        """
        with Vertical():
            count = len(self._items)
            plural = self._entity if count == 1 else f"{self._entity}s"
            yield Static(
                f"Found {count} similar {plural}",
                classes="dup-title",
            )
            for item in self._items:
                label = _escape_markup(str(item.get(self._label_key, "?")))
                title = _escape_markup(str(item.get("title") or item.get("name") or ""))
                yield Static(f"  {label}  {title}")
            yield Static(
                "\\[y]es create anyway  /  \\[n]o cancel",
                classes="dup-prompt",
            )

    def action_confirm(self) -> None:
        """
        Dismiss with ``True``: caller proceeds with creation.
        """
        self.dismiss(True)

    def action_cancel(self) -> None:
        """
        Dismiss with ``False``: caller aborts and flashes a notice.
        """
        self.dismiss(False)
