from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sara.core.loudness import LoudnessStandard
from sara.ui.dialogs import mix_point_loudness


def test_compute_normalization_gain_ebu(monkeypatch, tmp_path):
    def fake_analyze(_path: Path, *, standard: LoudnessStandard):
        assert standard is LoudnessStandard.EBU
        return SimpleNamespace(integrated_lufs=-18.0)

    monkeypatch.setattr(mix_point_loudness, "analyze_loudness", fake_analyze)
    gain, lufs = mix_point_loudness.compute_normalization_gain(tmp_path / "track.wav", standard=LoudnessStandard.EBU)
    assert lufs == -18.0
    assert gain == -5.0


def test_compute_normalization_gain_atsc(monkeypatch, tmp_path):
    def fake_analyze(_path: Path, *, standard: LoudnessStandard):
        assert standard is LoudnessStandard.ATSC
        return SimpleNamespace(integrated_lufs=-23.5)

    monkeypatch.setattr(mix_point_loudness, "analyze_loudness", fake_analyze)
    gain, lufs = mix_point_loudness.compute_normalization_gain(tmp_path / "track.wav", standard=LoudnessStandard.ATSC)
    assert lufs == -23.5
    assert gain == -0.5

