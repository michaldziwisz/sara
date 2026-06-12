from __future__ import annotations

import logging
import time
from types import SimpleNamespace

from sara.core.playlist import PlaylistItem
from sara.ui.playback.preview import start_mix_preview, stop_preview


class _DummyDevice:
    def __init__(self, device_id: str) -> None:
        self.id = device_id


class _DummyAudioEngine:
    def __init__(self, *, players: list[object], device_id: str) -> None:
        self._players = list(players)
        self._device = _DummyDevice(device_id)

    def get_devices(self):
        return [self._device]

    def refresh_devices(self) -> None:
        return None

    def create_player_instance(self, device_id: str):
        assert device_id == self._device.id
        return self._players.pop(0)


class _DummyPlayer:
    def __init__(self, *, supports_mix_trigger: bool = False) -> None:
        self._supports_mix_trigger = supports_mix_trigger
        self.preload_calls: list[tuple[str, float, bool]] = []
        self.play_calls: list[dict[str, object]] = []
        self.fade_calls: list[float] = []
        self.apply_mix_trigger_calls: list[tuple[float, object]] = []
        self.position_seconds = 0.0
        self.stopped = 0

    def set_gain_db(self, _gain_db) -> None:
        return None

    def preload(self, source_path: str, *, start_seconds: float = 0.0, allow_loop: bool = False) -> bool:
        self.preload_calls.append((source_path, float(start_seconds), bool(allow_loop)))
        return True

    def play(
        self,
        item_id: str,
        source_path: str,
        *,
        start_seconds: float = 0.0,
        allow_loop: bool = False,
        mix_trigger_seconds=None,
        on_mix_trigger=None,
    ):
        self.play_calls.append(
            {
                "item_id": item_id,
                "path": source_path,
                "start_seconds": float(start_seconds),
                "allow_loop": bool(allow_loop),
                "mix_trigger_seconds": mix_trigger_seconds,
                "on_mix_trigger": on_mix_trigger,
            }
        )
        return None

    def stop(self) -> None:
        self.stopped += 1

    def fade_out(self, _duration: float) -> None:
        self.fade_calls.append(float(_duration))

    def set_loop(self, _start_seconds, _end_seconds) -> None:
        return None

    def get_position_seconds(self) -> float:
        return self.position_seconds

    def _apply_mix_trigger(self, _mix_at_seconds: float, _callback) -> None:
        self.apply_mix_trigger_calls.append((_mix_at_seconds, _callback))

    def supports_mix_trigger(self) -> bool:
        return self._supports_mix_trigger


def test_pfl_mix_preview_preloads_next_track(tmp_path) -> None:
    device_id = "pfl-dev"
    path_a = tmp_path / "a.wav"
    path_a.write_text("a")
    path_b = tmp_path / "b.wav"
    path_b.write_text("b")

    current = PlaylistItem(id="a", path=path_a, title="A", duration_seconds=10.0)
    nxt = PlaylistItem(id="b", path=path_b, title="B", duration_seconds=8.0, cue_in_seconds=0.5)

    player_a = _DummyPlayer()
    player_b = _DummyPlayer()
    engine = _DummyAudioEngine(players=[player_a, player_b], device_id=device_id)

    controller = SimpleNamespace(
        _preview_context=None,
        _pfl_device_id=device_id,
        _settings=SimpleNamespace(get_pfl_device=lambda: device_id),
        _audio_engine=engine,
        _announce=lambda *_args, **_kwargs: None,
        _preload_enabled=True,
    )

    assert (
        start_mix_preview(
            controller,
            current,
            nxt,
            mix_at_seconds=4.0,
            pre_seconds=4.0,
            fade_seconds=0.0,
            current_effective_duration=None,
            next_cue_override=1.25,
        )
        is True
    )
    stop_preview(controller, wait=False)

    assert player_b.preload_calls == [(str(path_b), 1.25, False)]


def test_pfl_mix_preview_respects_preload_disable(tmp_path) -> None:
    device_id = "pfl-dev"
    path_a = tmp_path / "a.wav"
    path_a.write_text("a")
    path_b = tmp_path / "b.wav"
    path_b.write_text("b")

    current = PlaylistItem(id="a", path=path_a, title="A", duration_seconds=10.0)
    nxt = PlaylistItem(id="b", path=path_b, title="B", duration_seconds=8.0, cue_in_seconds=0.5)

    player_a = _DummyPlayer()
    player_b = _DummyPlayer()
    engine = _DummyAudioEngine(players=[player_a, player_b], device_id=device_id)

    controller = SimpleNamespace(
        _preview_context=None,
        _pfl_device_id=device_id,
        _settings=SimpleNamespace(get_pfl_device=lambda: device_id),
        _audio_engine=engine,
        _announce=lambda *_args, **_kwargs: None,
        _preload_enabled=False,
    )

    assert (
        start_mix_preview(
            controller,
            current,
            nxt,
            mix_at_seconds=4.0,
            pre_seconds=4.0,
            fade_seconds=0.0,
            current_effective_duration=None,
            next_cue_override=None,
        )
        is True
    )
    stop_preview(controller, wait=False)

    assert player_b.preload_calls == []


def test_pfl_mix_preview_arms_native_trigger_in_play_and_uses_cue_for_fade(tmp_path, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="sara.ui.playback.preview")

    device_id = "pfl-dev"
    path_a = tmp_path / "a.wav"
    path_a.write_text("a")
    path_b = tmp_path / "b.wav"
    path_b.write_text("b")

    current = PlaylistItem(id="a", path=path_a, title="A", duration_seconds=11.0, cue_in_seconds=1.0)
    nxt = PlaylistItem(id="b", path=path_b, title="B", duration_seconds=8.0, cue_in_seconds=0.5)

    player_a = _DummyPlayer(supports_mix_trigger=True)
    player_b = _DummyPlayer()
    engine = _DummyAudioEngine(players=[player_a, player_b], device_id=device_id)

    controller = SimpleNamespace(
        _preview_context=None,
        _pfl_device_id=device_id,
        _settings=SimpleNamespace(get_pfl_device=lambda: device_id),
        _audio_engine=engine,
        _announce=lambda *_args, **_kwargs: None,
        _preload_enabled=True,
        supports_mix_trigger=lambda player: player.supports_mix_trigger(),
    )

    assert (
        start_mix_preview(
            controller,
            current,
            nxt,
            mix_at_seconds=4.0,
            pre_seconds=2.0,
            fade_seconds=10.0,
            current_base_cue=1.0,
            current_effective_duration=10.0,
            next_cue_override=0.5,
        )
        is True
    )

    play_a = player_a.play_calls[0]
    assert play_a["start_seconds"] == 2.0
    assert play_a["mix_trigger_seconds"] == 4.0
    assert callable(play_a["on_mix_trigger"])
    assert player_a.apply_mix_trigger_calls == []

    player_a.position_seconds = 4.001
    play_a["on_mix_trigger"]()
    assert player_b.play_calls[0]["start_seconds"] == 0.5
    assert player_a.fade_calls == [7.0]
    assert "PFL mix preview: arming trigger native=True mix_at=4.000" in caplog.text
    assert "PFL mix preview: fire source=native mix_at=4.000" in caplog.text
    assert "a_pos=4.001" in caplog.text
    assert "PFL mix preview: next started source=native mix_at=4.000" in caplog.text

    stop_preview(controller, wait=False)


def test_pfl_mix_preview_defers_early_native_trigger_until_mix_position(tmp_path, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="sara.ui.playback.preview")

    device_id = "pfl-dev"
    path_a = tmp_path / "a.wav"
    path_a.write_text("a")
    path_b = tmp_path / "b.wav"
    path_b.write_text("b")

    current = PlaylistItem(id="a", path=path_a, title="A", duration_seconds=12.0)
    nxt = PlaylistItem(id="b", path=path_b, title="B", duration_seconds=8.0, cue_in_seconds=0.5)

    player_a = _DummyPlayer(supports_mix_trigger=True)
    player_b = _DummyPlayer()
    engine = _DummyAudioEngine(players=[player_a, player_b], device_id=device_id)

    controller = SimpleNamespace(
        _preview_context=None,
        _pfl_device_id=device_id,
        _settings=SimpleNamespace(get_pfl_device=lambda: device_id),
        _audio_engine=engine,
        _announce=lambda *_args, **_kwargs: None,
        _preload_enabled=True,
        supports_mix_trigger=lambda player: player.supports_mix_trigger(),
    )

    assert (
        start_mix_preview(
            controller,
            current,
            nxt,
            mix_at_seconds=4.0,
            pre_seconds=2.0,
            fade_seconds=1.4,
            next_cue_override=0.5,
        )
        is True
    )

    play_a = player_a.play_calls[0]
    player_a.position_seconds = 3.50
    play_a["on_mix_trigger"]()
    assert player_b.play_calls == []
    assert "PFL mix preview: native trigger early -> position wait mix_at=4.000 a_pos=3.500" in caplog.text

    player_a.position_seconds = 3.96
    deadline = time.time() + 1.0
    while not player_b.play_calls and time.time() < deadline:
        time.sleep(0.01)

    assert player_b.play_calls[0]["start_seconds"] == 0.5
    assert player_a.fade_calls == [1.4]
    assert "PFL mix preview: native position wait firing mix_at=4.000 a_pos=3.960" in caplog.text
    assert "PFL mix preview: fire source=native_wait mix_at=4.000" in caplog.text

    stop_preview(controller, wait=False)
