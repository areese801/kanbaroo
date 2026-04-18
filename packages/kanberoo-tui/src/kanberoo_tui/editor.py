"""
``$EDITOR`` integration helpers for the Kanberoo TUI.

Screens that collect multi-line markdown (story descriptions, new
comments, the new-story template on the board) drop into the user's
``$EDITOR`` with the same ``git commit`` idiom the CLI uses. Doing it
from inside an async Textual app adds two constraints the CLI version
does not have:

1. The app is painting the terminal. It must release it while the
   editor runs so the user sees the raw shell, and re-acquire it
   afterward. :meth:`textual.app.App.suspend` is Textual's built-in
   context manager for exactly this; it is synchronous, so we drive it
   from a worker thread via :func:`asyncio.to_thread` and the UI
   event loop stays responsive for anything (WebSocket frames, other
   screens) happening under it.
2. Tests cannot rely on a real editor subprocess. The helper takes a
   ``runner`` injection so test code can swap in a callable that
   rewrites the temp file directly, same shape as the CLI's
   ``_launch_editor`` substitute-via-``EDITOR=/bin/true`` trick but
   with a clean Python-level seam.

The helper returns ``None`` when the buffer is unchanged so callers
can short-circuit without issuing a REST call; this mirrors
``kanberoo_cli.commands.story._launch_editor``'s contract.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from textual.app import App, SuspendNotSupported

EditorRunner = Callable[["App[Any]", Path], Awaitable[None]]

DEFAULT_EDITOR = "vim"


async def _default_runner(app: App[Any], path: Path) -> None:
    """
    Default runner: suspend the Textual app and launch ``$EDITOR``.

    ``with app.suspend()`` is a synchronous context manager that
    redirects stdout/stderr back to the real terminal and blocks until
    the wrapped code returns; driving it from a worker thread via
    :func:`asyncio.to_thread` keeps the event loop free to queue any
    WebSocket frames that arrive while the editor is open. Drivers
    that do not support suspension (notably the headless driver used
    by Textual's ``run_test``) raise :class:`SuspendNotSupported`; we
    fall back to invoking the editor without suspending so the helper
    still works in that environment.
    """
    editor = os.environ.get("EDITOR", DEFAULT_EDITOR)

    def _run() -> None:
        try:
            with app.suspend():
                subprocess.run([editor, str(path)], check=True)
        except SuspendNotSupported:
            subprocess.run([editor, str(path)], check=True)

    await asyncio.to_thread(_run)


async def edit_markdown(
    app: App[Any],
    initial: str,
    *,
    suffix: str = ".md",
    runner: EditorRunner | None = None,
) -> str | None:
    """
    Drop into ``$EDITOR`` with ``initial`` prefilled and return the
    edited text.

    Writes ``initial`` to a fresh temp file with ``suffix``, hands the
    path to ``runner`` (default: suspend the app and launch
    ``$EDITOR``), reads the file back, and compares. Returns the new
    contents when they differ from ``initial`` and ``None`` when they
    do not so callers can distinguish "no changes, skip the PATCH"
    from "the user wrote nothing, abort".

    The temp file lives under ``$TMPDIR`` and is removed on the way
    out regardless of whether the editor succeeded.
    """
    runner = runner or _default_runner
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=suffix,
        delete=False,
        encoding="utf-8",
    ) as fh:
        fh.write(initial)
        temp_path = Path(fh.name)
    try:
        await runner(app, temp_path)
        edited = temp_path.read_text(encoding="utf-8")
    finally:
        temp_path.unlink(missing_ok=True)
    if edited == initial:
        return None
    return edited
