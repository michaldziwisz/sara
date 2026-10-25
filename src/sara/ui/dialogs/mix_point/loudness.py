"""Loudness helpers used by the mix point editor dialog."""

from __future__ import annotations

from pathlib import Path

from sara.core.loudness import LoudnessStandard, analyze_loudness, normalization_result


def compute_normalization_gain(track_path: Path, *, standard: LoudnessStandard) -> tuple[float, float]:
    """Return (gain_db, measured_lufs) for the selected loudness standard."""
    measurement = analyze_loudness(track_path, standard=standard)
    result = normalization_result(measurement, standard=standard)
    return result.gain_db, result.measured_lufs
