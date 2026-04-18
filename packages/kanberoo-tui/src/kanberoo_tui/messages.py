"""
Textual :class:`~textual.message.Message` subclasses used by the TUI.

Messages are the cross-cutting signalling primitive Textual exposes to
widgets and screens. Defining them centrally keeps the vocabulary in
one place and makes it easy to search for every publisher and every
handler from one file.

Two families live here:

* Navigation messages (``WorkspaceSelected``) posted by a screen to
  ask the app to push another screen.
* Live-update messages (``WsEventReceived``) posted by the app's
  WebSocket task so the active screen can decide whether to refetch.
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
