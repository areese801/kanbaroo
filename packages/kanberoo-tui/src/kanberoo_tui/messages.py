"""
Textual :class:`~textual.message.Message` subclasses used by the TUI.

Messages are the cross-cutting signalling primitive Textual exposes to
widgets and screens. Defining them centrally keeps the vocabulary in
one place and makes it easy to search for every publisher and every
handler from one file.

Three families live here:

* Navigation messages (``WorkspaceSelected``, ``StorySelected``,
  ``OpenSearch``, ``OpenAuditFeed``) posted by a screen to ask the
  app to push another screen.
* Live-update messages (``WsEventReceived``) posted by the app's
  WebSocket task so the active screen can decide whether to refetch.
* Refresh hints (``StoryMutated``) posted when a screen has made a
  mutation that the parent screen should observe optimistically
  without waiting for the WebSocket round-trip.
"""

from __future__ import annotations

from typing import Any

from textual.message import Message


class WorkspaceSelected(Message):
    """
    A row in the workspace list was picked.

    The app listens for this and pushes the board screen for the
    selected workspace. ``workspace`` is the raw REST body so the
    target screen has every field without refetching.
    """

    def __init__(self, workspace: dict[str, Any]) -> None:
        """
        Build the message carrying the selected workspace.
        """
        super().__init__()
        self.workspace = workspace


class StorySelected(Message):
    """
    A story was picked (card on the board, row in search results).

    The app listens and pushes the story detail screen. ``story`` is
    the raw REST body; the target screen refetches on mount anyway
    but uses this to render header chrome without a round-trip.
    """

    def __init__(self, story: dict[str, Any]) -> None:
        """
        Build the message carrying the selected story.
        """
        super().__init__()
        self.story = story


class OpenSearch(Message):
    """
    A screen asked to open the global fuzzy-search overlay.

    The app handles this by pushing :class:`SearchScreen`. Any screen
    bound to ``/`` can post it; the app does not need to know which.
    """


class OpenAuditFeed(Message):
    """
    A screen asked to open the global audit feed.

    The app handles this by pushing :class:`AuditFeedScreen`. Only the
    workspace list binds it in this milestone but other screens can
    emit it too.
    """


class WsEventReceived(Message):
    """
    The WebSocket task received a real event (pings are filtered out
    upstream in :mod:`kanberoo_tui.ws`).

    Screens listen for this and decide whether the event is relevant
    to them; the board screen, for example, refetches on any
    ``story.*`` event.
    """

    def __init__(self, event: dict[str, Any]) -> None:
        """
        Build the message wrapping a single event envelope.
        """
        super().__init__()
        self.event = event
