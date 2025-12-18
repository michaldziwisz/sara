"""DSP helpers for the software audio mixer."""

from __future__ import annotations

import logging

from sara.audio.mixer.types import MixerSource

logger = logging.getLogger(__name__)

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy should be available with soundfile
    np = None


def match_channels(data, channels: int):
    if data.shape[1] == channels:
        return data
    if data.shape[1] > channels:
        return data[:, :channels]
    pad_count = channels - data.shape[1]
    pad = np.repeat(data[:, -1:], pad_count, axis=1)
    return np.concatenate([data, pad], axis=1)


def snap_to_zero_crossing(sound_file, target_frame: int, *, window_frames: int) -> int:
    if target_frame <= 0 or window_frames <= 0:
        return max(0, target_frame)
    window = window_frames
    start = max(0, target_frame - window)
    try:
        sound_file.seek(start)
        data = sound_file.read(window * 2, dtype="float32", always_2d=True)
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Nie udało się pobrać okna zero-crossing: %s", exc)
        return max(0, target_frame)
    if data.size == 0:
        return max(0, target_frame)
    values = data[:, 0]
    crossings = [
        idx for idx in range(1, len(values)) if values[idx - 1] == 0 or values[idx - 1] * values[idx] <= 0
    ]
    if not crossings:
        return max(0, target_frame)
    desired = target_frame - start
    idx = min(crossings, key=lambda i: abs(i - desired))
    return start + idx


def apply_fades(source: MixerSource, data, frames_out: int, *, channels: int):
    if frames_out == 0:
        return data
    result = data

    if source.pending_fade_in > 0:
        frames = min(frames_out, source.pending_fade_in)
        fade = np.linspace(0.0, 1.0, frames, endpoint=False, dtype=result.dtype)
        result = result.copy()
        result[:frames] *= fade[:, None]
        source.pending_fade_in = max(0, source.pending_fade_in - frames)

    if source.fade_in_remaining > 0:
        frames = min(frames_out, source.fade_in_remaining)
        fade = np.linspace(0.0, 1.0, frames, endpoint=False, dtype=result.dtype)
        result = result.copy()
        result[:frames] *= fade[:, None]
        source.fade_in_remaining = max(0, source.fade_in_remaining - frames)

    if source.fade_out_remaining > 0:
        frames = min(frames_out, source.fade_out_remaining)
        fade = np.linspace(1.0, 0.0, frames, endpoint=False, dtype=result.dtype)
        result = result.copy()
        result[-frames:] *= fade[:, None]
        source.fade_out_remaining = max(0, source.fade_out_remaining - frames)
        if source.fade_out_remaining == 0:
            source.buffer = np.zeros((0, channels), dtype=np.float32)

    return result
