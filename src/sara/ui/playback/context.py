"""Shared playback context models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sara.audio.engine import Player


@dataclass
class PlaybackContext:
    player: Player
    path: Path
    device_id: str
    slot_index: int
    intro_seconds: float | None = None
    intro_alert_triggered: bool = False
    track_end_alert_triggered: bool = False

