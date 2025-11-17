from pathlib import Path

import pytest

from sara.core.loudness import LoudnessStandard, analyze_loudness, find_bs1770gain


@pytest.mark.skipif(find_bs1770gain() is None, reason="bs1770gain not available")
def test_analyze_loudness_returns_value() -> None:
    measurement = analyze_loudness(Path("src/sara/audio/media/beep.wav"), standard=LoudnessStandard.EBU)
    assert isinstance(measurement.integrated_lufs, float)
