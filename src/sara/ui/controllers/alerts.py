"""Compatibility wrapper for playback alert helpers.

Implementation lives in `sara.ui.controllers.playback.alerts`.
"""

from __future__ import annotations

from sara.ui.controllers.playback.alerts import (
    announce_intro_remaining,
    announce_track_end_remaining,
    cleanup_intro_alert_player,
    cleanup_track_end_alert_player,
    compute_intro_remaining,
    consider_intro_alert,
    consider_track_end_alert,
    logger,
    play_intro_alert,
    play_track_end_alert,
)

__all__ = [
    "announce_intro_remaining",
    "announce_track_end_remaining",
    "cleanup_intro_alert_player",
    "cleanup_track_end_alert_player",
    "compute_intro_remaining",
    "consider_intro_alert",
    "consider_track_end_alert",
    "logger",
    "play_intro_alert",
    "play_track_end_alert",
]

