from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, List, Optional

from sara.core.config import SettingsManager
from sara.core.playlist import PlaylistItem, PlaylistModel, PlaylistKind
from sara.ui.playback_controller import PlaybackController


@dataclass
class DummyDevice:
    id: str
    name: str = "Device"
    backend: str | None = None


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

    def play(self, playlist_item_id: str, source_path: str, *, start_seconds: float = 0.0, **_kwargs):
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
        self._devices = [DummyDevice("dev-1", "Main Device"), DummyDevice("dev-2", "Alt")]
        self.created_players: List[DummyPlayer] = []

    def get_devices(self):
        return self._devices

    def refresh_devices(self):
        return None

    def create_player(self, device_id: str):
        player = DummyPlayer(device_id)
        self.created_players.append(player)
        return player


class DummyMixer:
    def __init__(self, device: DummyDevice):
        self.device = device
        self.started: list[tuple[str, str, float]] = []
        self.faded: list[float] = []
        self.stopped: list[str] = []
        self.updated_callbacks: list[tuple[Optional[Callable], Optional[Callable]]] = []

    def start_source(
        self,
        source_id: str,
        path: str,
        *,
        start_seconds: float = 0.0,
        gain_db=None,
        loop=None,
        on_progress=None,
        on_finished=None,
    ):
        self.started.append((source_id, path, start_seconds))
        self._finished = on_finished
        self._progress = on_progress
        return Event()

    def fade_out_source(self, _source_id: str, duration: float):
        self.faded.append(duration)

    def stop_source(self, source_id: str):
        self.stopped.append(source_id)
        if hasattr(self, "_finished") and self._finished:
            self._finished(source_id)

    def pause_source(self, source_id: str):
        self.stopped.append(f"pause-{source_id}")

    def set_gain_db(self, _source_id: str, _gain_db):
        return None

    def set_loop(self, _source_id: str, _loop):
        return None

    def update_callbacks(self, *_args, **_kwargs):
        progress = _kwargs.get("on_progress")
        finished = _kwargs.get("on_finished")
        self.updated_callbacks.append((progress, finished))
        if finished is not None:
            self._finished = finished
        if progress is not None:
            self._progress = progress


class DummyMixerPlayer:
    def __init__(self, mixer: DummyMixer):
        self._mixer = mixer
        self._finished = None
        self._progress = None
        self._gain = None
        self._loop = None

    def play(
        self,
        playlist_item_id: str,
        source_path: str,
        *,
        start_seconds: float = 0.0,
        allow_loop: bool = False,
        mix_trigger_seconds: float | None = None,
        on_mix_trigger=None,
    ):
        return self._mixer.start_source(
            playlist_item_id,
            source_path,
            start_seconds=start_seconds,
            on_progress=self._progress,
            on_finished=self._finished,
        )

    def fade_out(self, duration: float):
        self._mixer.fade_out_source("dummy", duration)

    def set_finished_callback(self, callback):
        self._finished = callback

    def set_progress_callback(self, callback):
        self._progress = callback

    def set_gain_db(self, gain_db):
        self._gain = gain_db

    def set_loop(self, start_seconds, end_seconds):
        self._loop = (start_seconds, end_seconds)


def _playlist_with_item(tmp_path, slots: tuple[str, ...] = ("dev-1",)) -> tuple[PlaylistModel, PlaylistItem]:
    playlist = PlaylistModel(id="pl-1", name="Test", kind=PlaylistKind.MUSIC)
    playlist.set_output_slots(list(slots))
    track_path = tmp_path / "track.mp3"
    track_path.write_text("dummy")
    item = PlaylistItem(id="item-1", path=track_path, title="Track", duration_seconds=10.0)
    playlist.add_items([item])
    return playlist, item


def test_start_item_acquires_player_and_registers_context(tmp_path):
    playlist, item = _playlist_with_item(tmp_path, slots=("dev-1", "dev-2"))
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
    playlist, item = _playlist_with_item(tmp_path, slots=("dev-1", "dev-2"))
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


def test_single_slot_uses_device_mixer_and_fade(monkeypatch, tmp_path):
    playlist, item = _playlist_with_item(tmp_path)
    audio = DummyAudioEngine()
    settings = SettingsManager(config_path=tmp_path / "settings.yaml")
    mixers: dict[str, DummyMixer] = {}

    def mixer_factory(device):
        mixer = DummyMixer(device)
        mixers[device.id] = mixer
        return mixer

    # make sure mixer is only imported when needed
    monkeypatch.syspath_prepend(str(tmp_path / "nonexistent"))

    controller = PlaybackController(audio, settings, lambda *_args: None, mixer_factory=mixer_factory)
    controller._get_mixer_player_class = lambda: DummyMixerPlayer  # type: ignore[attr-defined]

    controller.start_item(
        playlist,
        item,
        start_seconds=0.0,
        on_finished=lambda _item_id: None,
        on_progress=lambda _item_id, _seconds: None,
    )

    assert mixers["dev-1"].started == [(item.id, str(item.path), 0.0)]
    removed = controller.stop_playlist(playlist.id, fade_duration=0.5)
    assert removed
    assert mixers["dev-1"].faded == [0.5]


def test_clear_auto_mix_and_get_context(tmp_path):
    playlist, item = _playlist_with_item(tmp_path)
    audio = DummyAudioEngine()
    settings = SettingsManager(config_path=tmp_path / "settings.yaml")
    controller = PlaybackController(
        audio,
        settings,
        lambda *_args: None,
        mixer_factory=lambda device: DummyMixer(device),
    )

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
