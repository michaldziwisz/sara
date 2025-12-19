"""Backward-compatible import path for options dialogs.

The implementation lives in `sara.ui.dialogs.options_dialog`.
"""

from __future__ import annotations

from sara.ui.dialogs.options_dialog import OptionsDialog, StartupPlaylistDialog

__all__ = [
    "OptionsDialog",
    "StartupPlaylistDialog",
]

