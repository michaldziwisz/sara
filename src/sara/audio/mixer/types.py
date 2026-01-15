"""Shared types/helpers for the software audio mixer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable, Optional

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy should be available with soundfile
    np = None

# Small fade to mask offset/loop clicks
MICRO_FADE_SECONDS = 0.004
# Window to look for a nearby zero-crossing when starting playback
ZERO_CROSS_WINDOW_SECONDS = 0.005


class NullOutputStream:
    """Fallback OutputStream used when sounddevice is not available."""

    def __init__(self, samplerate: float, channels: int, writes: Optional[list] = None):
        self.samplerate = samplerate
        self.channels = channels
        self._writes = writes

    def write(self, data) -> None:  # pragma: no cover - trivial
        if self._writes is not None and np is not None:
            self._writes.append(np.array(data, copy=True))

    def __enter__(self) -> "NullOutputStream":  # pragma: no cover - trivial
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # pragma: no cover - trivial
        return False


@dataclass
class MixerSource:
    source_id: str
    path: Path
    sound_file: object
    samplerate: int
    channels: int
    resample_ratio: float
    buffer: object
    gain: float = 1.0
    loop_range: Optional[tuple[int, int]] = None
    fade_in_remaining: int = 0
    fade_out_remaining: int = 0
    pending_fade_in: int = 0
    paused: bool = False
    stop_requested: bool = False
    position_frames: int = 0
    finished_event: Event = field(default_factory=Event)
    on_progress: Optional[Callable[[str, float], None]] = None
    on_finished: Optional[Callable[[str], None]] = None
    transcoded_path: Path | None = None
