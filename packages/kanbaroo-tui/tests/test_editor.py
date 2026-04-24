"""
Tests for the ``$EDITOR`` helper.

Only the pure temp-file plumbing is exercised here. Screen-level
tests in :mod:`test_story_detail` and :mod:`test_board_new_story`
cover the wiring into actual mutation flows.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

from kanbaroo_tui.editor import _default_runner, edit_markdown


class _FakeApp:
    """
    Tiny stand-in for ``textual.app.App``.

    The editor helper never reaches into app internals beyond
    calling ``app.suspend``; the default runner is bypassed in every
    test via a custom runner, so the attribute is never touched.
    """


async def test_edit_returns_none_on_unchanged_buffer():
    app = _FakeApp()
    captured: list[Path] = []

    async def runner(_app: Any, path: Path) -> None:
        captured.append(path)

    result = await edit_markdown(app, "hello", runner=runner)
    assert result is None
    assert len(captured) == 1
    # Temp file should have been removed.
    assert not captured[0].exists()


async def test_edit_returns_new_contents_when_changed():
    app = _FakeApp()

    async def runner(_app: Any, path: Path) -> None:
        path.write_text("rewritten", encoding="utf-8")

    result = await edit_markdown(app, "hello", runner=runner)
    assert result == "rewritten"


async def test_edit_returns_none_on_empty_rewrite_matching_initial():
    app = _FakeApp()

    async def runner(_app: Any, path: Path) -> None:
        path.write_text("", encoding="utf-8")

    # Initial is empty; writing empty again means "no change".
    result = await edit_markdown(app, "", runner=runner)
    assert result is None


async def test_edit_cleans_up_temp_file_on_runner_failure():
    app = _FakeApp()
    captured: list[Path] = []

    class _Boom(Exception):
        pass

    async def runner(_app: Any, path: Path) -> None:
        captured.append(path)
        raise _Boom("editor crashed")

    with contextlib.suppress(_Boom):
        await edit_markdown(app, "hello", runner=runner)
    assert captured
    assert not captured[0].exists()


class _FakeSuspendContext:
    """
    Stand-in for the return value of ``App.suspend()``.

    Records enter/exit so the test can assert the context is entered
    on the same task that calls the runner (i.e. on the event loop
    thread).
    """

    def __init__(self) -> None:
        """
        Build a fresh, unentered context.
        """
        self.entered: bool = False
        self.exited: bool = False

    def __enter__(self) -> _FakeSuspendContext:
        """
        Record entry; return self for the ``as`` binding if used.
        """
        self.entered = True
        return self

    def __exit__(self, *_exc: Any) -> None:
        """
        Record exit.
        """
        self.exited = True


class _FakeAppWithSuspend:
    """
    Stand-in for ``App`` that exposes ``suspend()`` and ``refresh()``.

    Tracks the calls so the test can verify the default runner enters
    the suspend context synchronously (on the event loop) and only
    offloads the blocking subprocess to a thread.
    """

    def __init__(self) -> None:
        """
        Build the fake with one reusable suspend context and no refresh.
        """
        self.suspend_ctx = _FakeSuspendContext()
        self.refreshed: bool = False

    def suspend(self) -> _FakeSuspendContext:
        """
        Return the fake suspend context manager.
        """
        return self.suspend_ctx

    def refresh(self) -> None:
        """
        Record that the app was asked to repaint post-editor.
        """
        self.refreshed = True


async def test_default_runner_offloads_subprocess_to_thread(tmp_path):
    """
    ``_default_runner`` enters ``app.suspend()`` on the event loop
    thread and runs the editor subprocess via ``asyncio.to_thread``.

    Regression guard for the editor-crash fix: previously suspend was
    entered from a worker thread, leaving the terminal in a bad state
    when the subprocess unwound.
    """
    app = _FakeAppWithSuspend()
    target = tmp_path / "msg.md"
    target.write_text("seed", encoding="utf-8")
    observed: list[object] = []

    def _fake_run(cmd, check: bool = False):  # type: ignore[no-untyped-def]
        observed.append(("run", tuple(cmd), check))

        class _Completed:
            returncode = 0

        return _Completed()

    with patch("kanbaroo_tui.editor.subprocess.run", _fake_run):
        await _default_runner(app, target)
    assert app.suspend_ctx.entered
    assert app.suspend_ctx.exited
    assert app.refreshed
    assert observed
    assert observed[0][0] == "run"
