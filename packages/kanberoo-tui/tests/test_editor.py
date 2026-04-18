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

from kanberoo_tui.editor import edit_markdown


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
