"""
Single-story card shown inside a :class:`BoardColumn`.

The card is the smallest focusable unit on the board: keyboard
navigation ends on a card, move mode targets the currently-focused
card, and the visible state of the board is the set of cards rendered
in each column. Rendering is intentionally flat (one :class:`Static`
subclass, no nested widgets) so focus handling stays obvious.

See ``docs/spec.md`` section 8.1 for the card content contract:
human id, title, priority badge, actor badge for the last state
transition, and tag chips. Tag colours are rendered as plain labels
when the story list response does not carry colour data; cage H does
not fan out extra requests to the tags endpoint.
"""

from __future__ import annotations

import os
from typing import Any

from textual.widgets import Static

PRIORITY_STYLES: dict[str, str] = {
    "none": "dim",
    "low": "bold #7faa3a",
    "medium": "bold yellow",
    "high": "bold red",
}

ACTOR_EMOJI: dict[str, str] = {
    "human": "\U0001f464",
    "claude": "\U0001f916",
    "system": "\u2699\ufe0f",
}

ACTOR_LABELS: dict[str, str] = {
    "human": "h",
    "claude": "c",
    "system": "s",
}

ACTOR_STYLES: dict[str, str] = {
    "human": "bold",
    "claude": "bold magenta",
    "system": "dim",
}


def _terminal_supports_emoji() -> bool:
    """
    Return ``True`` when the current ``$TERM`` is expected to render
    multi-byte glyphs.

    Crude but workable: ``linux`` (the kernel VT) and ``dumb`` both
    fall back to ASCII; every other ``$TERM`` value is assumed to
    render emoji. An unset ``$TERM`` is treated as capable so
    :func:`run_test` and other headless harnesses render glyphs rather
    than fallbacks.
    """
    term = os.environ.get("TERM", "")
    if not term:
        return True
    lowered = term.lower()
    if lowered == "dumb":
        return False
    return "linux" not in lowered


def actor_badge(actor_type: str) -> str:
    """
    Return the display glyph for ``actor_type``.

    Prefers the emoji set when the terminal is expected to render it,
    falls back to the single-character labels otherwise. Unknown actor
    types yield ``"?"`` so no empty string ever lands in a card.
    """
    if _terminal_supports_emoji():
        return ACTOR_EMOJI.get(actor_type, ACTOR_LABELS.get(actor_type, "?"))
    return ACTOR_LABELS.get(actor_type, "?")


def _truncate(text: str, *, max_length: int) -> str:
    """
    Shorten ``text`` to ``max_length`` characters with an ellipsis.

    Used for story titles so a long title does not blow out a narrow
    column in a cramped terminal.
    """
    if len(text) <= max_length:
        return text
    if max_length <= 1:
        return text[:max_length]
    return text[: max_length - 1] + "\u2026"


class StoryCard(Static):
    """
    One story rendered as a card inside a board column.

    ``story`` is the raw REST body for the story. ``tags`` is an
    optional list of tag dicts (``name``, ``color``) indexed by story
    id; if absent, tag chips render as plain labels.
    """

    DEFAULT_CSS = """
    StoryCard {
        height: auto;
        padding: 0 1;
        margin: 1 0;
        border: round $panel-lighten-1;
        background: $surface;
    }
    StoryCard:focus {
        border: heavy $accent;
        background: $boost;
    }
    """

    can_focus = True

    def __init__(
        self,
        story: dict[str, Any],
        *,
        tags: list[dict[str, Any]] | None = None,
        id: str | None = None,
    ) -> None:
        """
        Build a card around ``story``. ``tags`` is optional.
        """
        super().__init__(id=id)
        self._story = story
        self._tags = tags or []

    @property
    def story(self) -> dict[str, Any]:
        """
        Return the underlying story dict so callers (the board screen,
        move mode, tests) can read fields off the card without a
        separate lookup.
        """
        return self._story

    def on_mount(self) -> None:
        """
        Render the card content once Textual has attached us to the
        DOM. Rendering in :meth:`__init__` would run before
        :class:`Static` finishes its own setup.
        """
        self.update(self._build_markup())

    def _build_markup(self) -> str:
        """
        Build a Textual markup string for the card.

        Lines:

        1. ``KAN-7  [priority]  [actor]``
        2. truncated title
        3. tag chips (optional)
        """
        human_id = str(self._story.get("human_id", "?"))
        priority = str(self._story.get("priority", "none"))
        priority_style = PRIORITY_STYLES.get(priority, "dim")
        parts = [f"[bold]{human_id}[/bold]"]
        parts.append(f"  [{priority_style}]\\[{priority}][/{priority_style}]")
        actor_type = self._story.get("state_actor_type")
        if actor_type:
            badge = actor_badge(str(actor_type))
            actor_style = ACTOR_STYLES.get(str(actor_type), "bold")
            parts.append(f"  [{actor_style}]{badge}[/{actor_style}]")
        title = _truncate(str(self._story.get("title", "")), max_length=80)
        # Escape any accidental markup characters in user text.
        safe_title = title.replace("[", "\\[")
        parts.append(f"\n{safe_title}")
        if self._tags:
            chip_parts: list[str] = []
            for tag in self._tags:
                name = str(tag.get("name", "")).replace("[", "\\[")
                chip_parts.append(f"[cyan]#{name}[/cyan]")
            parts.append("\n" + " ".join(chip_parts))
        return "".join(parts)
