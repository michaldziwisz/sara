"""Lifecycle helpers for mixer sources.

This module extracts the non-threaded, deterministic parts of starting/replacing
sources from `DeviceMixer` to keep that class smaller.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Callable, Optional

from sara.audio.mixer.dsp import snap_to_zero_crossing
from sara.audio.mixer.types import MixerSource
from sara.audio.types import AudioDevice

logger = logging.getLogger(__name__)

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy should be available with soundfile
    np = None


def open_sound_file(path: str, *, sf):
    if sf is None:
        raise RuntimeError("soundfile is required for DeviceMixer")
    return sf.SoundFile(path, mode="r")


def get_sound_file_format(sound_file, *, default_samplerate: int, default_channels: int) -> tuple[int, int]:
    samplerate = int(getattr(sound_file, "samplerate", None) or default_samplerate)
    channels = int(getattr(sound_file, "channels", None) or default_channels)
    return samplerate, channels


def resolve_output_samplerate(
    *,
    sd,
    device: AudioDevice,
    output_samplerate: int,
    output_channels: int,
    file_samplerate: int,
    logger: Optional[logging.Logger] = None,
) -> int:
    if logger is None:
        logger = logging.getLogger(__name__)
    if sd is None or device.raw_index is None:
        return output_samplerate
    try:
        sd.check_output_settings(
            device=device.raw_index,
            samplerate=float(output_samplerate),
            channels=output_channels,
        )
    except Exception:  # pylint: disable=broad-except
        logger.debug(
            "Urządzenie %s nie wspiera %s Hz - fallback do %s",
            device.name,
            output_samplerate,
            file_samplerate,
        )
        return file_samplerate
    return output_samplerate


def prepare_start_frame(
    sound_file,
    *,
    start_seconds: float,
    samplerate: int,
    zero_cross_frames: int,
) -> int:
    start_frame = int(max(0.0, start_seconds) * samplerate)
    start_frame = snap_to_zero_crossing(sound_file, start_frame, window_frames=zero_cross_frames)
    try:
        sound_file.seek(start_frame)
    except Exception:  # pylint: disable=broad-except
        sound_file.seek(0)
        start_frame = 0
    return start_frame


def compute_gain_factor(gain_db: Optional[float]) -> float:
    if gain_db is None:
        return 1.0
    try:
        return math.pow(10.0, max(min(gain_db, 18.0), -60.0) / 20.0)
    except Exception:  # pylint: disable=broad-except
        return 1.0


def compute_loop_frames(loop: Optional[tuple[float, float]], *, samplerate: int) -> Optional[tuple[int, int]]:
    if loop is None:
        return None
    loop_start = max(0, int(loop[0] * samplerate))
    loop_end = max(loop_start + 1, int(loop[1] * samplerate))
    return (loop_start, loop_end)


def create_source(
    *,
    source_id: str,
    path: str,
    sound_file,
    file_samplerate: int,
    file_channels: int,
    output_samplerate: int,
    output_channels: int,
    micro_fade_frames: int,
    zero_cross_frames: int,
    start_seconds: float,
    gain_db: Optional[float],
    loop: Optional[tuple[float, float]],
    on_progress: Optional[Callable[[str, float], None]],
    on_finished: Optional[Callable[[str], None]],
) -> MixerSource:
    start_frame = prepare_start_frame(
        sound_file,
        start_seconds=start_seconds,
        samplerate=file_samplerate,
        zero_cross_frames=zero_cross_frames,
    )
    resample_ratio = float(output_samplerate) / float(file_samplerate or 1)
    gain = compute_gain_factor(gain_db)
    loop_range = compute_loop_frames(loop, samplerate=file_samplerate)

    return MixerSource(
        source_id=source_id,
        path=Path(path),
        sound_file=sound_file,
        samplerate=file_samplerate,
        channels=file_channels,
        resample_ratio=resample_ratio,
        buffer=np.zeros((0, output_channels), dtype=np.float32),
        gain=gain,
        loop_range=loop_range,
        fade_in_remaining=micro_fade_frames,
        stop_requested=False,
        on_progress=on_progress,
        on_finished=on_finished,
        position_frames=start_frame,
    )


def dispose_replaced_source(source: MixerSource) -> None:
    try:
        source.sound_file.close()
    except Exception:  # pylint: disable=broad-except
        pass
    source.finished_event.set()
