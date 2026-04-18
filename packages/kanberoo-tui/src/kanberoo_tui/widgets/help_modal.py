"""
Shared ``?`` keybinding help overlay.

Cage H wired ``?`` to flash a placeholder. This module replaces that
with a real :class:`ModalScreen` each screen configures with its own
table of keys. One implementation keeps the look consistent across
the workspace list, board, story detail, search, and audit feed;
adding a new screen only requires declaring a list of
``(key, description)`` pairs and passing it to :class:`KeybindingHelp`.

Usage from a screen:

``await self.app.push_screen(KeybindingHelp(title="Board", bindings=[...]))``

Dismissal is bound to ``escape``, ``q``, and ``?`` so the user can
toggle the overlay with the same key that opened it.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

KeyBindingRow = tuple[str, str]


class KeybindingHelp(ModalScreen[None]):
    """
    Overlay that lists the bindings for the screen underneath it.

    ``title`` names the host screen in the header. ``bindings`` is a
    list of ``(key, description)`` tuples, rendered as-is into a
    :class:`DataTable`; formatting of the key (e.g. ``ctrl+c``) is the
    caller's responsibility so the overlay can reflect whatever label
    the caller's :class:`~textual.binding.Binding` uses in its
    ``description``.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss_help", "Close", priority=True),
        Binding("q", "dismiss_help", "Close"),
        Binding("question_mark", "dismiss_help", "Close"),
    ]

    DEFAULT_CSS = """
    KeybindingHelp {
        align: center middle;
    }
    KeybindingHelp > Vertical {
        width: 60;
        max-width: 80%;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $panel;
        padding: 1 2;
    }
    KeybindingHelp .help-title {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    KeybindingHelp DataTable {
        height: auto;
    }
    """

    def __init__(
        self,
        *,
        title: str,
        bindings: list[KeyBindingRow],
    ) -> None:
        """
        Build a modal overlay titled ``title`` listing ``bindings``.
        """
        super().__init__()
        self._title_text = title
        self._rows = list(bindings)

    def compose(self) -> ComposeResult:
        """
        Lay out the centered panel: title line, key table.
        """
        with Vertical():
            yield Static(
                f"Keybindings: {self._title_text}",
                classes="help-title",
            )
            table: DataTable[str] = DataTable(
                id="help-table",
                cursor_type="row",
                zebra_stripes=True,
                show_header=True,
            )
            table.add_columns("key", "action")
            yield table

    def on_mount(self) -> None:
        """
        Populate the table once the modal is in the DOM.
        """
        table = self.query_one("#help-table", DataTable)
        for key, description in self._rows:
            table.add_row(key, description)

    def action_dismiss_help(self) -> None:
        """
        Pop the modal off the stack.
        """
        self.dismiss(None)
