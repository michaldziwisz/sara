"""Small resampling helpers shared by audio components."""

from __future__ import annotations

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy instalowane z soundfile
    np = None


def _resample_to_length(block, target_frames: int):
    if np is None or target_frames <= 0:
        return block
    src_frames = block.shape[0]
    if src_frames == 0 or src_frames == target_frames:
        return block
    if src_frames == 1:
        return np.repeat(block, target_frames, axis=0).astype(block.dtype, copy=False)
    src_idx = np.arange(src_frames, dtype=np.float64)
    target_idx = np.linspace(0.0, src_frames - 1, target_frames, dtype=np.float64)
    resampled = np.empty((target_frames, block.shape[1]), dtype=np.float32)
    for channel in range(block.shape[1]):
        resampled[:, channel] = np.interp(target_idx, src_idx, block[:, channel])
    return resampled.astype(block.dtype, copy=False)

