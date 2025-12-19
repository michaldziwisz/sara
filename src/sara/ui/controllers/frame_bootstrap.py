"""Compatibility wrapper for MainFrame bootstrap helpers.

Implementation lives in `sara.ui.controllers.frame.bootstrap`.
"""

from __future__ import annotations

from sara.ui.controllers.frame.bootstrap import (
    init_audio_controllers,
    init_command_ids,
    init_playlist_state,
    init_runtime_state,
    init_settings,
    init_ui,
)

__all__ = [
    "init_audio_controllers",
    "init_command_ids",
    "init_playlist_state",
    "init_runtime_state",
    "init_settings",
    "init_ui",
]

