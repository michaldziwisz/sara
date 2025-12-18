"""Compatibility wrapper for auto-mix helpers.

Implementation lives in `sara.ui.controllers.playback.automix`.
"""

from __future__ import annotations

from sara.ui.controllers.playback.automix import (
    ANNOUNCEMENT_PREFIX,
    auto_mix_play_next,
    auto_mix_start_index,
    logger,
    preferred_auto_mix_index,
    set_auto_mix_enabled,
)

__all__ = [
    "ANNOUNCEMENT_PREFIX",
    "auto_mix_play_next",
    "auto_mix_start_index",
    "logger",
    "preferred_auto_mix_index",
    "set_auto_mix_enabled",
]

