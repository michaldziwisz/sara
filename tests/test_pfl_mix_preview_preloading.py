from __future__ import annotations

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
    def __init__(self) -> None:
        self.preload_calls: list[tuple[str, float, bool]] = []
        self.play_calls: list[tuple[str, str, float, bool]] = []
        self.stopped = 0

    def set_gain_db(self, _gain_db) -> None:
        return None

    def preload(self, source_path: str, *, start_seconds: float = 0.0, allow_loop: bool = False) -> bool:
        self.preload_calls.append((source_path, float(start_seconds), bool(allow_loop)))
        return True

    def play(self, item_id: str, source_path: str, *, start_seconds: float = 0.0, allow_loop: bool = False):
        self.play_calls.append((item_id, source_path, float(start_seconds), bool(allow_loop)))
        return None

    def stop(self) -> None:
        self.stopped += 1

    def fade_out(self, _duration: float) -> None:
        return None

    def set_loop(self, _start_seconds, _end_seconds) -> None:
        return None

    def _apply_mix_trigger(self, _mix_at_seconds: float, _callback) -> None:
        return None


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

