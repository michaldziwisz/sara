from pathlib import Path

import pytest

from sara.ui.file_selection_dialog import ensure_save_selection, parse_file_wildcard


def test_parse_file_wildcard_produces_pairs():
    filters = parse_file_wildcard("MP3|*.mp3|WAV|*.wav")
    assert filters[0][0] == "MP3"
    assert filters[0][1] == ["*.mp3"]
    assert filters[1][0] == "WAV"
    assert filters[1][1] == ["*.wav"]


def test_parse_file_wildcard_falls_back_to_all_files():
    filters = parse_file_wildcard("invalid")
    assert filters[0][1] == ["*.*"]


def test_ensure_save_selection_requires_name(tmp_path):
    with pytest.raises(ValueError):
        ensure_save_selection(tmp_path, "")
    path = ensure_save_selection(tmp_path, "track.mp3")[0]
    assert path.endswith("track.mp3")
    assert Path(path).parent == tmp_path
