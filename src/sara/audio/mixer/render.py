"""Source rendering for the software audio mixer."""

from __future__ import annotations

import logging
import math

from sara.audio.mixer.dsp import apply_fades, match_channels
from sara.audio.mixer.types import MixerSource
from sara.audio.resampling import _resample_to_length

logger = logging.getLogger(__name__)

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy should be available with soundfile
    np = None


def render_source(
    source: MixerSource,
    *,
    block_size: int,
    channels: int,
    micro_fade_frames: int,
):
    output = np.zeros((block_size, channels), dtype=np.float32)
    finished = False
    frames_out = 0

    if source.paused:
        return output, frames_out, finished

    if source.stop_requested and source.fade_out_remaining == 0:
        return output, frames_out, True

    buffer = source.buffer

    target_block = block_size
    if source.stop_requested and source.fade_out_remaining > 0:
        target_block = min(target_block, source.fade_out_remaining)

    while len(buffer) < target_block:
        remaining = target_block - len(buffer)
        need_src = max(1, int(math.ceil(remaining / max(source.resample_ratio, 1e-6))))
        try:
            data = source.sound_file.read(need_src, dtype="float32", always_2d=True)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Błąd odczytu pliku %s: %s", source.path, exc)
            finished = True
            break

        frames_read = len(data)
        if frames_read == 0:
            finished = True
            break

        loop_range = source.loop_range
        if loop_range and source.position_frames + frames_read >= loop_range[1]:
            frames_allowed = loop_range[1] - source.position_frames
            frames_allowed = max(0, frames_allowed)
            if frames_allowed < frames_read:
                data = data[:frames_allowed]
                frames_read = frames_allowed
            try:
                source.sound_file.seek(loop_range[0])
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Błąd ustawienia pętli: %s", exc)
                source.loop_range = None
            else:
                source.pending_fade_in = max(source.pending_fade_in, micro_fade_frames)
            source.position_frames = loop_range[0]
        else:
            source.position_frames += frames_read

        data = match_channels(data, channels)
        if abs(source.resample_ratio - 1.0) > 1e-6:
            target_frames = max(1, int(round(frames_read * source.resample_ratio)))
            data = _resample_to_length(data, target_frames)

        if len(buffer) == 0:
            buffer = data
        else:
            buffer = np.concatenate([buffer, data], axis=0)

    if len(buffer) >= block_size:
        output = buffer[:block_size]
        buffer = buffer[block_size:]
        frames_out = len(output)
    else:
        frames_out = len(buffer)
        if frames_out:
            output[:frames_out] = buffer
        finished = True
        buffer = np.zeros((0, channels), dtype=np.float32)

    output = apply_fades(source, output, frames_out, channels=channels)
    if source.stop_requested and source.fade_out_remaining == 0:
        finished = True
        source.buffer = np.zeros((0, channels), dtype=np.float32)
    output = output * float(source.gain)
    source.buffer = buffer
    return output, frames_out, finished
