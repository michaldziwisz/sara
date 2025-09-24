"""Tests for loop metadata persistence in audio files."""

from __future__ import annotations

from pathlib import Path

import pytest

from sara.core.media_metadata import extract_metadata, save_loop_metadata


@pytest.mark.parametrize("start,end", [(1.5, 3.25), (0.0, 2.0)])
def test_save_loop_metadata_roundtrip(tmp_path, start, end) -> None:
    audio_path = tmp_path / "sample.mp3"
    audio_path.touch()

    assert save_loop_metadata(audio_path, start, end, True)

    metadata = extract_metadata(audio_path)
    assert metadata.loop_start_seconds == pytest.approx(start, rel=1e-6)
    assert metadata.loop_end_seconds == pytest.approx(end, rel=1e-6)
    assert metadata.loop_enabled is True

    assert save_loop_metadata(audio_path, start, end, False)
    metadata = extract_metadata(audio_path)
    assert metadata.loop_start_seconds == pytest.approx(start, rel=1e-6)
    assert metadata.loop_end_seconds == pytest.approx(end, rel=1e-6)
    assert metadata.loop_enabled is False

    assert save_loop_metadata(audio_path, None, None)
    metadata = extract_metadata(audio_path)
    assert metadata.loop_start_seconds is None
    assert metadata.loop_end_seconds is None
    assert metadata.loop_enabled is False
