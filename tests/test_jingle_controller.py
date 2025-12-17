from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sara.jingles import JinglePage, JingleSet, JingleSlot, save_jingle_set
from sara.ui.jingle_controller import JingleController


class DummyPlayer:
    def __init__(self) -> None:
        self.gain_db = "unset"
        self.play_calls: list[tuple[str, str]] = []

    def is_active(self) -> bool:
        return False

    def stop(self) -> None:
        return None

    def fade_out(self, _duration: float) -> None:
        return None

    def set_gain_db(self, gain_db):  # noqa: ANN001 - test double
        self.gain_db = gain_db

    def play(self, playlist_item_id: str, source_path: str, *, start_seconds: float = 0.0, allow_loop: bool = True):
        self.play_calls.append((playlist_item_id, source_path))
        return None


class DummyAudioEngine:
    def __init__(self) -> None:
        self.main_player = DummyPlayer()
        self.instance_players: list[DummyPlayer] = []

    def create_player(self, _device_id: str) -> DummyPlayer:
        return self.main_player

    def create_player_instance(self, _device_id: str) -> DummyPlayer:
        player = DummyPlayer()
        self.instance_players.append(player)
        return player

    def get_devices(self):  # noqa: ANN001 - test double
        return [SimpleNamespace(id="dummy")]


class DummySettings:
    def __init__(self, *, device_id: str = "dummy") -> None:
        self._device_id = device_id

    def get_jingles_device(self) -> str | None:
        return self._device_id

    def get_playback_fade_seconds(self) -> float:
        return 0.0


def _write_jingle_set(set_path: Path, audio_path: Path) -> None:
    save_jingle_set(
        set_path,
        JingleSet(pages=[JinglePage(slots=[JingleSlot(path=audio_path)])]),
    )


def test_jingle_play_sets_replaygain(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "jingle.wav"
    audio_path.write_bytes(b"a")
    set_path = tmp_path / "jingles.sarajingles"
    save_jingle_set(
        set_path,
        JingleSet(pages=[JinglePage(slots=[JingleSlot(path=audio_path, replay_gain_db=-6.5)])]),
    )

    engine = DummyAudioEngine()
    settings = DummySettings()

    controller = JingleController(engine, settings, lambda *_args: None, set_path=set_path)
    assert controller.play_slot(0) is True
    assert engine.main_player.gain_db == -6.5


def test_jingle_play_resets_gain_when_missing(tmp_path: Path) -> None:
    audio_path = tmp_path / "jingle.wav"
    audio_path.write_bytes(b"a")
    set_path = tmp_path / "jingles.sarajingles"
    save_jingle_set(
        set_path,
        JingleSet(pages=[JinglePage(slots=[JingleSlot(path=audio_path, replay_gain_db=-3.0)])]),
    )

    engine = DummyAudioEngine()
    settings = DummySettings()
    controller = JingleController(engine, settings, lambda *_args: None, set_path=set_path)

    assert controller.play_slot(0) is True
    assert engine.main_player.gain_db == -3.0

    controller.jingle_set.pages[0].slots[0].replay_gain_db = None  # type: ignore[union-attr]
    assert controller.play_slot(0) is True
    assert engine.main_player.gain_db is None


def test_jingle_overlay_applies_replaygain(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "jingle.wav"
    audio_path.write_bytes(b"a")
    set_path = tmp_path / "jingles.sarajingles"
    save_jingle_set(
        set_path,
        JingleSet(pages=[JinglePage(slots=[JingleSlot(path=audio_path, replay_gain_db=-9.0)])]),
    )

    engine = DummyAudioEngine()
    settings = DummySettings()

    controller = JingleController(engine, settings, lambda *_args: None, set_path=set_path)
    assert controller.play_slot(0, overlay=True) is True
    assert engine.instance_players
    assert engine.instance_players[-1].gain_db == -9.0
