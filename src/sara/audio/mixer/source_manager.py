"""Thread-safe management of mixer sources."""

from __future__ import annotations

import math
from threading import Lock
from typing import Callable, Dict, Optional

from sara.audio.mixer.types import MixerSource

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy should be available with soundfile
    np = None


class MixerSourceManager:
    def __init__(self) -> None:
        self._sources: Dict[str, MixerSource] = {}
        self._lock = Lock()

    def snapshot(self) -> list[MixerSource]:
        with self._lock:
            return list(self._sources.values())

    def replace(self, source: MixerSource) -> Optional[MixerSource]:
        with self._lock:
            old = self._sources.pop(source.source_id, None)
            self._sources[source.source_id] = source
            return old

    def pop(self, source_id: str) -> Optional[MixerSource]:
        with self._lock:
            return self._sources.pop(source_id, None)

    def clear(self) -> list[MixerSource]:
        with self._lock:
            sources = list(self._sources.values())
            self._sources.clear()
            return sources

    def is_empty(self) -> bool:
        with self._lock:
            return not self._sources

    def set_gain_db(self, source_id: str, gain_db: Optional[float]) -> None:
        with self._lock:
            source = self._sources.get(source_id)
            if not source:
                return
            if gain_db is None:
                source.gain = 1.0
                return
            try:
                source.gain = math.pow(10.0, max(min(gain_db, 18.0), -60.0) / 20.0)
            except Exception:  # pylint: disable=broad-except
                source.gain = 1.0

    def set_loop(self, source_id: str, loop: Optional[tuple[float, float]]) -> None:
        with self._lock:
            source = self._sources.get(source_id)
            if not source:
                return
            if loop is None:
                source.loop_range = None
                return
            start, end = loop
            samplerate = source.samplerate or 1
            start_frame = max(0, int(start * samplerate))
            end_frame = max(start_frame + 1, int(end * samplerate))
            source.loop_range = (start_frame, end_frame)

    def pause(self, source_id: str) -> None:
        with self._lock:
            source = self._sources.get(source_id)
            if source:
                source.paused = True

    def resume(self, source_id: str) -> bool:
        with self._lock:
            source = self._sources.get(source_id)
            if not source:
                return False
            was_paused = source.paused
            source.paused = False
            return was_paused

    def fade_out(self, source_id: str, duration: float, *, samplerate: int, channels: int) -> bool:
        with self._lock:
            source = self._sources.get(source_id)
            if not source:
                return False
            if duration <= 0.0:
                source.fade_out_remaining = 0
                if np is not None:
                    source.buffer = np.zeros((0, channels), dtype=np.float32)
                source.paused = False
                source.stop_requested = True
                return False
            frames = max(1, int(samplerate * duration))
            source.fade_out_remaining = frames
            source.stop_requested = True
            return True

    def update_callbacks(
        self,
        source_id: str,
        *,
        on_progress: Optional[Callable[[str, float], None]] = None,
        on_finished: Optional[Callable[[str], None]] = None,
    ) -> None:
        with self._lock:
            source = self._sources.get(source_id)
            if not source:
                return
            source.on_progress = on_progress
            source.on_finished = on_finished
