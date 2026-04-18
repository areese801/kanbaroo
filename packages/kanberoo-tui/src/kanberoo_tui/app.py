"""
Kanberoo TUI application.

The :class:`KanberooTuiApp` owns the long-lived HTTP client and the
WebSocket subscriber task and pushes screens to drive the user
through the workspace list into the board view. It is intentionally
thin: every screen fetches its own data and owns its own bindings;
the app's job is to wire them together, route WebSocket events to
the active screen, and shut everything down cleanly on exit.

Dependency injection
--------------------

``client_factory`` and ``ws_factory`` are constructor arguments so
tests can point either at a fake without touching the network.
Production code calls :func:`main` which loads the config from disk
and uses the default factories.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator, Callable
from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.widgets import Static

from kanberoo_tui.client import AsyncApiClient
from kanberoo_tui.config import (
    ConfigError,
    ConfigNotFoundError,
    TuiConfig,
    load_config,
)
from kanberoo_tui.editor import EditorRunner
from kanberoo_tui.messages import (
    EpicSelected,
    OpenAuditFeed,
    OpenEpicList,
    OpenSearch,
    StorySelected,
    WorkspaceSelected,
    WsEventReceived,
)
from kanberoo_tui.screens.audit_feed import AuditFeedScreen
from kanberoo_tui.screens.board import BoardScreen
from kanberoo_tui.screens.epic_detail import EpicDetailScreen
from kanberoo_tui.screens.epic_list import EpicListScreen
from kanberoo_tui.screens.search import SearchScreen
from kanberoo_tui.screens.story_detail import StoryDetailScreen
from kanberoo_tui.screens.workspace_list import WorkspaceListScreen
from kanberoo_tui.ws import EventSubscriber, build_events_url

ClientFactory = Callable[[TuiConfig], AsyncApiClient]
WsFactory = Callable[[TuiConfig], AsyncIterator[dict[str, Any]]]


def default_client_factory(config: TuiConfig) -> AsyncApiClient:
    """
    Build the real :class:`AsyncApiClient` from config.
    """
    return AsyncApiClient(base_url=config.api_url, token=config.token)


def default_ws_factory(config: TuiConfig) -> AsyncIterator[dict[str, Any]]:
    """
    Build the real WebSocket event stream.

    Returns a fresh async iterator each call so the app can restart
    the subscription without leaking the previous generator.
    """
    url = build_events_url(config.api_url, config.token)
    subscriber = EventSubscriber(url=url)
    return subscriber.stream()


class KanberooTuiApp(App[None]):
    """
    Top-level Textual app for Kanberoo.

    Accepts the config and the two factories so tests can construct
    an app instance with fakes and drive it through ``run_test``.
    """

    TITLE = "Kanberoo"
    SUB_TITLE = "board"

    CSS: ClassVar[str] = """
    """

    def __init__(
        self,
        *,
        config: TuiConfig,
        client_factory: ClientFactory | None = None,
        ws_factory: WsFactory | None = None,
        editor_runner: EditorRunner | None = None,
    ) -> None:
        """
        Build the app bound to ``config``.

        ``editor_runner`` is forwarded to every screen that launches
        ``$EDITOR`` (board ``n``, story detail ``e``/``c``). Tests pass
        a callable that rewrites the temp file directly so no real
        editor subprocess is launched; production callers leave it
        ``None`` and each screen falls back to the default runner.
        """
        super().__init__()
        self._config = config
        self._client_factory = client_factory or default_client_factory
        self._ws_factory = ws_factory or default_ws_factory
        self._editor_runner = editor_runner
        self._client: AsyncApiClient | None = None
        self._ws_task: asyncio.Task[None] | None = None
        self._ws_listeners: list[Any] = []

    @property
    def editor_runner(self) -> EditorRunner | None:
        """
        Return the editor runner configured at construction time, if
        any. Screens read this when their own runner is ``None``.
        """
        return self._editor_runner

    @property
    def client(self) -> AsyncApiClient:
        """
        Return the shared HTTP client. Screens read this; calling
        before :meth:`on_mount` has created the client is a bug, so we
        raise a clear error rather than silently returning ``None``.
        """
        if self._client is None:
            raise RuntimeError("AsyncApiClient not initialized yet")
        return self._client

    def compose(self) -> ComposeResult:
        """
        Compose an empty placeholder: the real content lives on
        screens pushed from :meth:`on_mount`.
        """
        yield Static("")

    async def on_mount(self) -> None:
        """
        Create the HTTP client, start the WS subscriber, push the
        workspace list.
        """
        self._client = self._client_factory(self._config)
        self._ws_task = asyncio.create_task(self._run_ws())
        await self.push_screen(WorkspaceListScreen())

    async def on_unmount(self) -> None:
        """
        Shut down the WS task and close the HTTP client.
        """
        if self._ws_task is not None:
            self._ws_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._ws_task
            self._ws_task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _run_ws(self) -> None:
        """
        Drain the WebSocket stream and post each event back to the
        app so handlers can run on the event loop.
        """
        try:
            stream = self._ws_factory(self._config)
            async for event in stream:
                self.post_message(WsEventReceived(event))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.log(f"ws task error: {exc}")

    def register_ws_listener(self, listener: Any) -> None:
        """
        Register ``listener`` to receive WebSocket events.

        ``listener`` must expose an async ``handle_ws_event(event)``
        method. Registration is idempotent (double-registration is a
        no-op); screens call this from ``on_mount`` and its counterpart
        :meth:`unregister_ws_listener` from ``on_unmount``.
        """
        if listener not in self._ws_listeners:
            self._ws_listeners.append(listener)

    def unregister_ws_listener(self, listener: Any) -> None:
        """
        Remove ``listener`` from the WebSocket event fan-out.
        """
        if listener in self._ws_listeners:
            self._ws_listeners.remove(listener)

    async def on_ws_event_received(self, message: WsEventReceived) -> None:
        """
        Fan out a received event to every registered listener.

        Textual resolves the handler by snake-casing the message's
        class name, so ``WsEventReceived`` maps to
        ``on_ws_event_received``.
        """
        for listener in list(self._ws_listeners):
            handler = getattr(listener, "handle_ws_event", None)
            if handler is None:
                continue
            await handler(message.event)

    async def on_workspace_selected(self, message: WorkspaceSelected) -> None:
        """
        Push the board screen for the workspace in ``message``.
        """
        await self.push_screen(
            BoardScreen(message.workspace, editor_runner=self._editor_runner)
        )

    async def on_story_selected(self, message: StorySelected) -> None:
        """
        Push the story detail screen for the story in ``message``.
        """
        await self.push_screen(
            StoryDetailScreen(message.story, editor_runner=self._editor_runner)
        )

    async def on_open_search(self, message: OpenSearch) -> None:
        """
        Push the global fuzzy-search overlay.
        """
        del message
        await self.push_screen(SearchScreen())

    async def on_open_audit_feed(self, message: OpenAuditFeed) -> None:
        """
        Push the global audit feed screen.
        """
        del message
        await self.push_screen(AuditFeedScreen())

    async def on_open_epic_list(self, message: OpenEpicList) -> None:
        """
        Push the epic list screen for the workspace in ``message``.
        """
        await self.push_screen(EpicListScreen(message.workspace))

    async def on_epic_selected(self, message: EpicSelected) -> None:
        """
        Push the epic detail screen for the selected epic.
        """
        await self.push_screen(EpicDetailScreen(message.workspace, message.epic))


def main() -> None:
    """
    Synchronous entry point for the ``kanberoo-tui`` console script.

    Reads config from disk, prints a friendly hint if the file is
    missing, and starts the Textual app. Any other
    :class:`ConfigError` exits with code 1 so the user's shell sees a
    non-zero status.
    """
    try:
        config = load_config()
    except ConfigNotFoundError as exc:
        print(
            f"Kanberoo config not found at {exc.path}.\nRun `kb init` to create one.",
            file=sys.stderr,
        )
        sys.exit(1)
    except ConfigError as exc:
        print(f"Kanberoo config error: {exc}", file=sys.stderr)
        sys.exit(1)
    app = KanberooTuiApp(config=config)
    app.run()
