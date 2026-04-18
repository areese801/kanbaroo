"""
One state column on the board view.

A column is a vertical scrollable container that holds a header
(state label plus card count) followed by zero or more
:class:`~kanberoo_tui.widgets.story_card.StoryCard` widgets. Columns
themselves are not focusable: focus lives on the cards, and the board
screen walks the column's ``query(StoryCard)`` result to move focus
with ``h``/``l``.
"""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import Static

from kanberoo_tui.widgets.story_card import StoryCard


class BoardColumn(VerticalScroll):
    """
    Vertical scrollable container for a single state.

    The column tracks its ``state_key`` (``backlog``, ``todo``, ...)
    and its human-readable ``title`` so tests and the board screen can
    address columns by state without reaching into CSS ids.
    """

    DEFAULT_CSS = """
    BoardColumn {
        width: 1fr;
        height: 1fr;
        border: round $panel;
        padding: 0 1;
    }
    BoardColumn > .column-header {
        color: $accent;
        text-style: bold;
        padding: 0 1;
        height: 1;
    }
    """

    def __init__(
        self,
        *,
        state_key: str,
        title: str,
        id: str | None = None,
    ) -> None:
        """
        Build an empty column. Cards are added through :meth:`set_cards`
        so the board can atomically replace the set on refresh.
        """
        super().__init__(id=id)
        self.state_key: str = state_key
        self._title = title
        self._cards: list[StoryCard] = []

    def on_mount(self) -> None:
        """
        Mount the column header once Textual attaches the widget.
        """
        header = Static(self._header_text(), classes="column-header")
        self.mount(header)

    def _header_text(self) -> str:
        """
        Format the column header. Separated so :meth:`set_cards` can
        re-render it without rebuilding the widget.
        """
        return f"{self._title} ({len(self._cards)})"

    def set_cards(self, cards: list[StoryCard]) -> None:
        """
        Replace the current set of cards with ``cards``.

        Removes every existing :class:`StoryCard` child and mounts the
        new list in order. The header is re-rendered so the count
        matches the new set.
        """
        for existing in list(self.query(StoryCard)):
            existing.remove()
        self._cards = list(cards)
        for card in self._cards:
            self.mount(card)
        header = self.query(".column-header").first()
        if isinstance(header, Static):
            header.update(self._header_text())

    @property
    def cards(self) -> list[StoryCard]:
        """
        Return the current list of cards in render order.
        """
        return list(self._cards)
