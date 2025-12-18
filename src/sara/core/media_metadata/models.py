"""Shared data structures for media metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class AudioMetadata:
    title: str
    duration_seconds: float
    artist: Optional[str] = None
    replay_gain_db: Optional[float] = None
    cue_in_seconds: Optional[float] = None
    segue_seconds: Optional[float] = None
    segue_fade_seconds: Optional[float] = None
    overlap_seconds: Optional[float] = None
    intro_seconds: Optional[float] = None
    outro_seconds: Optional[float] = None
    loop_start_seconds: Optional[float] = None
    loop_end_seconds: Optional[float] = None
    loop_auto_enabled: bool = False
    loop_enabled: bool = False

