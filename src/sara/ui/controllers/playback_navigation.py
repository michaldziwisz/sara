"""Compatibility wrapper for playback navigation helpers.

Implementation lives in `sara.ui.controllers.playback.navigation`.
"""

from __future__ import annotations

from sara.ui.controllers.playback.navigation import (
    adjust_duration_and_mix_trigger,
    derive_next_play_index,
    handle_playback_progress,
    index_of_item,
    logger,
    manual_fade_duration,
    on_global_play_next,
    play_next_alternate,
)

__all__ = [
    "adjust_duration_and_mix_trigger",
    "derive_next_play_index",
    "handle_playback_progress",
    "index_of_item",
    "logger",
    "manual_fade_duration",
    "on_global_play_next",
    "play_next_alternate",
]

