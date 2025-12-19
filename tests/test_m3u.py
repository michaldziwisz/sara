from __future__ import annotations

from pathlib import Path

from sara.core.m3u import parse_m3u_lines, serialize_m3u
from sara.core.playlist import PlaylistItem


def test_parse_m3u_lines_extracts_extinf_metadata() -> None:
    lines = [
        "#EXTM3U",
        "",
        " #EXTM3U  ",
        "#EXTINF:123,Artist - Title",
        "C:\\music\\track.mp3",
        "#EXTINF:-1,No duration",
        "relative.flac",
        "#EXTINF:bad,Bad duration",
        "bad.wav",
        "#EXTINF:10",
        "no-title.mp3",
        "plain.mp3",
    ]

    entries = parse_m3u_lines(lines)

    assert entries[0] == {"path": "C:\\music\\track.mp3", "title": "Artist - Title", "duration": 123.0}
    assert entries[1] == {"path": "relative.flac", "title": "No duration", "duration": None}
    assert entries[2] == {"path": "bad.wav", "title": "Bad duration", "duration": None}
    assert entries[3] == {"path": "no-title.mp3", "title": None, "duration": 10.0}
    assert entries[4] == {"path": "plain.mp3", "title": None, "duration": None}


def test_serialize_m3u_matches_main_frame_format(tmp_path: Path) -> None:
    path_one = tmp_path / "one.mp3"
    path_two = tmp_path / "two.mp3"
    path_one.write_text("x", encoding="utf-8")
    path_two.write_text("x", encoding="utf-8")

    items = [
        PlaylistItem(id="1", path=path_one, title="One", duration_seconds=12.7),
        PlaylistItem(id="2", path=path_two, title="Two", duration_seconds=0.0),
    ]

    serialized = serialize_m3u(items).splitlines()

    assert serialized[0] == "#EXTM3U"
    assert serialized[1] == "#EXTINF:12,One"
    assert serialized[2] == str(path_one.resolve())
    assert serialized[3] == "#EXTINF:-1,Two"
    assert serialized[4] == str(path_two.resolve())

