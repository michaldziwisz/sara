"""Compatibility wrapper for edit/clipboard/undo actions.

Implementation lives in `sara.ui.controllers.playlists.edit_actions`.
"""

from __future__ import annotations

from sara.ui.controllers.playlists.edit_actions import (
    apply_undo_callback,
    finalize_clipboard_paste,
    logger,
    move_selection,
    on_copy_selection,
    on_cut_selection,
    on_delete_selection,
    on_paste_selection,
    on_redo,
    on_undo,
    push_undo_action,
)

__all__ = [
    "apply_undo_callback",
    "finalize_clipboard_paste",
    "logger",
    "move_selection",
    "on_copy_selection",
    "on_cut_selection",
    "on_delete_selection",
    "on_paste_selection",
    "on_redo",
    "on_undo",
    "push_undo_action",
]

