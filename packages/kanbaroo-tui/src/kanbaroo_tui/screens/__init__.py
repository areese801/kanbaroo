"""
Screen classes used by the TUI app.

The board screen imports from this package so callers can reach it
without hunting through submodules.
"""

from kanbaroo_tui.screens.board import BoardScreen
from kanbaroo_tui.screens.workspace_list import WorkspaceListScreen

__all__ = ["BoardScreen", "WorkspaceListScreen"]
