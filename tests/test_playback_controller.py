from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from sara.core.config import SettingsManager
from sara.core.playlist import PlaylistItem, PlaylistModel, PlaylistKind
from sara.ui.playback_controller import PlaybackController


@dataclass
class DummyDevice:
    id: str
    name: str = "Device"


class DummyPlayer:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.play_calls: List[tuple[str, str, float]] = []
        self.finished_callback: Optional[Callable[[str], None]] = None
        self.progress_callback: Optional[Callable[[str, float], None]] = None
        self.gain = None
        self.loop = None
        self.stopped = False
        self.fade_calls: List[float] = []

    def play(self, playlist_item_id: str, source_path: str, *, start_seconds: float = 0.0):
        self.play_calls.append((playlist_item_id, source_path, start_seconds))

    def set_finished_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        self.finished_callback = callback

    def set_progress_callback(self, callback: Optional[Callable[[str, float], None]]) -> None:
        self.progress_callback = callback

    def set_gain_db(self, gain_db):
        self.gain = gain_db

    def set_loop(self, start_seconds, end_seconds):
        self.loop = (start_seconds, end_seconds)

    def stop(self):
        self.stopped = True

    def fade_out(self, duration: float):
        self.fade_calls.append(duration)


class DummyAudioEngine:
    def __init__(self):
        self._devices = [DummyDevice("dev-1", "Main Device")]
        self.created_players: List[DummyPlayer] = []

    def get_devices(self):
        return self._devices

    def refresh_devices(self):
        return None

    def create_player(self, device_id: str):
        player = DummyPlayer(device_id)
        self.created_players.append(player)
        return player


def _playlist_with_item(tmp_path) -> tuple[PlaylistModel, PlaylistItem]:
    playlist = PlaylistModel(id="pl-1", name="Test", kind=PlaylistKind.MUSIC)
    playlist.set_output_slots(["dev-1"])
    track_path = tmp_path / "track.mp3"
    track_path.write_text("dummy")
    item = PlaylistItem(id="item-1", path=track_path, title="Track", duration_seconds=10.0)
    playlist.add_items([item])
    return playlist, item


def test_start_item_acquires_player_and_registers_context(tmp_path):
    playlist, item = _playlist_with_item(tmp_path)
    audio = DummyAudioEngine()
    settings = SettingsManager(config_path=tmp_path / "settings.yaml")
    controller = PlaybackController(audio, settings, lambda *_args: None)

    context = controller.start_item(
        playlist,
        item,
        start_seconds=0.0,
        on_finished=lambda _item_id: None,
        on_progress=lambda _item_id, _seconds: None,
    )

    assert context is not None
    player = audio.created_players[0]
    assert player.play_calls == [(item.id, str(item.path), 0.0)]
    assert controller.contexts[(playlist.id, item.id)].device_id == "dev-1"


def test_stop_playlist_fades_out_and_clears_context(tmp_path):
    playlist, item = _playlist_with_item(tmp_path)
    audio = DummyAudioEngine()
    settings = SettingsManager(config_path=tmp_path / "settings.yaml")
    controller = PlaybackController(audio, settings, lambda *_args: None)

    controller.start_item(
        playlist,
        item,
        start_seconds=0.0,
        on_finished=lambda _item_id: None,
        on_progress=lambda _item_id, _seconds: None,
    )

    removed = controller.stop_playlist(playlist.id, fade_duration=1.5)
    assert removed
    assert controller.contexts == {}
    player = audio.created_players[0]
    assert player.fade_calls == [1.5]
    assert player.stopped is False  # fade_out used instead of stop


def test_clear_auto_mix_and_get_context(tmp_path):
    playlist, item = _playlist_with_item(tmp_path)
    audio = DummyAudioEngine()
    settings = SettingsManager(config_path=tmp_path / "settings.yaml")
    controller = PlaybackController(audio, settings, lambda *_args: None)

    controller.start_item(
        playlist,
        item,
        start_seconds=0.0,
        on_finished=lambda _item_id: None,
        on_progress=lambda _item_id, _seconds: None,
    )
    key = (playlist.id, item.id)
    controller.auto_mix_state[key] = True
    assert controller.get_context(playlist.id)[0] == key
    controller.clear_auto_mix()
    assert controller.auto_mix_state == {}
