"""Compatibility wrapper for the options dialog.

Implementation lives in `sara.ui.dialogs.options.dialog`.
"""

from __future__ import annotations

from sara.ui.dialogs.options.dialog import OptionsDialog
from sara.ui.dialogs.options.startup_playlist_dialog import StartupPlaylistDialog

__all__ = [
    "OptionsDialog",
    "StartupPlaylistDialog",
]
