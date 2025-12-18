"""Compatibility wrapper for loop/remaining-time helpers.

Implementation lives in `sara.ui.controllers.playback.loop`.
"""

from __future__ import annotations

from sara.ui.controllers.playback.loop import (
    active_playlist_item,
    apply_loop_setting_to_playback,
    logger,
    on_loop_info,
    on_toggle_loop_playback,
    on_track_remaining,
    resolve_remaining_playback,
    sync_loop_mix_trigger,
)

__all__ = [
    "active_playlist_item",
    "apply_loop_setting_to_playback",
    "logger",
    "on_loop_info",
    "on_toggle_loop_playback",
    "on_track_remaining",
    "resolve_remaining_playback",
    "sync_loop_mix_trigger",
]

