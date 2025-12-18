"""Loudness helpers used by the mix point editor dialog."""

from __future__ import annotations

from pathlib import Path

from sara.core.loudness import LoudnessStandard, analyze_loudness


def compute_normalization_gain(track_path: Path, *, standard: LoudnessStandard) -> tuple[float, float]:
    """Return (gain_db, measured_lufs) for the selected loudness standard."""
    measurement = analyze_loudness(track_path, standard=standard)
    target_lufs = -23.0 if standard is LoudnessStandard.EBU else -24.0
    gain_db = target_lufs - measurement.integrated_lufs
    return gain_db, measurement.integrated_lufs

