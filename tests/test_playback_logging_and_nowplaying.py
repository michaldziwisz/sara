from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

from sara.core.config import SettingsManager
from sara.core.playlist import PlaylistItem, PlaylistItemType, PlaylistKind, PlaylistModel
from sara.ui.services.now_playing import NowPlayingWriter
from sara.ui.services.playback_logging import PlayedTracksLogger


def test_played_tracks_logger_writes_hourly_csv(tmp_path: Path) -> None:
    settings = SettingsManager(config_path=tmp_path / "settings.yaml")
    settings.set_played_tracks_logging_enabled(True)
    settings.set_played_tracks_logging_songs_enabled(True)
    settings.set_played_tracks_logging_spots_enabled(False)

    output_dir = tmp_path / "output"
    service = PlayedTracksLogger(settings, output_dir=output_dir)

    playlist = PlaylistModel(id="pl-1", name="Music", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="it-1",
        path=Path("track.mp3"),
        title="Title",
        artist="Artist",
        duration_seconds=200.0,
        cue_in_seconds=10.0,
        item_type=PlaylistItemType.SONG,
    )
    started_at = datetime(2025, 1, 2, 13, 45, 6)
    service.on_started(playlist, item, started_at=started_at)
    service.on_progress(playlist.id, item.id, 110.0)  # includes cue_in
    service.on_finished(playlist, item, finished_at=started_at + timedelta(seconds=100))

    log_path = output_dir / "logs" / "2025" / "01" / "02" / "13.csv"
    assert log_path.exists()

    with log_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == ["artist", "title", "played_at", "played_seconds"]
    assert rows[1][0] == "Artist"
    assert rows[1][1] == "Title"
    assert rows[1][2] == "2025-01-02 13:45:06"
    assert rows[1][3] == "100.000"


def test_played_tracks_logger_respects_spot_toggle(tmp_path: Path) -> None:
    settings = SettingsManager(config_path=tmp_path / "settings.yaml")
    settings.set_played_tracks_logging_enabled(True)
    settings.set_played_tracks_logging_songs_enabled(True)
    settings.set_played_tracks_logging_spots_enabled(False)

    output_dir = tmp_path / "output"
    service = PlayedTracksLogger(settings, output_dir=output_dir)

    playlist = PlaylistModel(id="pl-1", name="Music", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="it-1",
        path=Path("spot.mp3"),
        title="Spot",
        artist=None,
        duration_seconds=30.0,
        item_type=PlaylistItemType.SPOT,
    )
    started_at = datetime(2025, 1, 2, 13, 0, 0)
    service.on_started(playlist, item, started_at=started_at)
    service.on_progress(playlist.id, item.id, 5.0)
    service.on_finished(playlist, item, finished_at=started_at + timedelta(seconds=5))

    assert not (output_dir / "logs").exists()


def test_now_playing_writer_writes_on_track_change_and_clears(tmp_path: Path) -> None:
    settings = SettingsManager(config_path=tmp_path / "settings.yaml")
    settings.set_now_playing_enabled(True)
    settings.set_now_playing_update_on_track_change(True)
    settings.set_now_playing_update_interval_seconds(0.0)
    settings.set_now_playing_template("%artist - %title")

    output_dir = tmp_path / "output"
    writer = NowPlayingWriter(settings, output_dir=output_dir)

    playlist = PlaylistModel(id="pl-1", name="Music", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="it-1",
        path=Path("track.mp3"),
        title="Title",
        artist="Artist",
        duration_seconds=200.0,
        item_type=PlaylistItemType.SONG,
    )

    writer.on_started(playlist, item, started_at=datetime(2025, 1, 2, 13, 0, 0))
    now_path = output_dir / "nowplaying.txt"
    assert now_path.read_text(encoding="utf-8") == "Artist - Title\n"

    writer.on_finished(playlist.id, item.id)
    assert now_path.read_text(encoding="utf-8") == ""

def test_now_playing_writer_respects_type_filters(tmp_path: Path) -> None:
    settings = SettingsManager(config_path=tmp_path / "settings.yaml")
    settings.set_now_playing_enabled(True)
    settings.set_now_playing_update_on_track_change(True)
    settings.set_now_playing_update_interval_seconds(0.0)
    settings.set_now_playing_template("%title")
    settings.set_now_playing_songs_enabled(True)
    settings.set_now_playing_spots_enabled(False)

    output_dir = tmp_path / "output"
    writer = NowPlayingWriter(settings, output_dir=output_dir)

    playlist = PlaylistModel(id="pl-1", name="Music", kind=PlaylistKind.MUSIC)
    spot = PlaylistItem(
        id="it-spot",
        path=Path("spot.mp3"),
        title="Spot",
        artist=None,
        duration_seconds=30.0,
        item_type=PlaylistItemType.SPOT,
    )

    writer.on_started(playlist, spot, started_at=datetime(2025, 1, 2, 13, 0, 0))
    now_path = output_dir / "nowplaying.txt"
    assert now_path.read_text(encoding="utf-8") == ""


def test_now_playing_writer_periodic_updates(tmp_path: Path) -> None:
    settings = SettingsManager(config_path=tmp_path / "settings.yaml")
    settings.set_now_playing_enabled(True)
    settings.set_now_playing_update_on_track_change(False)
    settings.set_now_playing_update_interval_seconds(5.0)
    settings.set_now_playing_template("%title")

    output_dir = tmp_path / "output"

    writes: list[str] = []

    class _Clock:
        def __init__(self) -> None:
            self.t = 0.0

        def monotonic(self) -> float:
            return self.t

    clock = _Clock()

    def _writer(_path: Path, text: str) -> None:
        writes.append(text)

    service = NowPlayingWriter(settings, output_dir=output_dir, monotonic=clock.monotonic, writer=_writer)

    playlist = PlaylistModel(id="pl-1", name="Music", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="it-1",
        path=Path("track.mp3"),
        title="Title",
        artist="Artist",
        duration_seconds=200.0,
        item_type=PlaylistItemType.SONG,
    )

    service.on_started(playlist, item, started_at=datetime(2025, 1, 2, 13, 0, 0))
    assert writes == []

    clock.t = 0.0
    service.on_progress(playlist.id, item.id, 1.0)
    assert writes == ["Title\n"]

    clock.t = 3.0
    service.on_progress(playlist.id, item.id, 4.0)
    assert writes == ["Title\n"]

    clock.t = 5.0
    service.on_progress(playlist.id, item.id, 6.0)
    assert writes == ["Title\n", "Title\n"]
