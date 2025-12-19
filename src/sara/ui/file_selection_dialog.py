"""Backward-compatible import path for `FileSelectionDialog`.

The implementation lives in `sara.ui.dialogs.file_selection.dialog`.
"""

from __future__ import annotations

from sara.ui.dialogs.file_selection_dialog import FileSelectionDialog, ensure_save_selection, parse_file_wildcard

__all__ = [
    "FileSelectionDialog",
    "ensure_save_selection",
    "parse_file_wildcard",
]
