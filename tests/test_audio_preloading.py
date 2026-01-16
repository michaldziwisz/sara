from __future__ import annotations

from pathlib import Path
from threading import Event

from sara.audio.bass.player import flow as bass_flow


class _DummyContext:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


class _DummyManager:
    def __init__(self) -> None:
        self.created: list[tuple[int, Path, bool]] = []
        self.played: list[int] = []
        self.positions: list[tuple[int, float]] = []
        self.acquired: int = 0

    def acquire_device(self, _index: int) -> _DummyContext:
        self.acquired += 1
        return _DummyContext()

    def stream_create_file(self, index: int, path: Path, *, allow_loop: bool = False, **_kwargs) -> int:
        self.created.append((index, path, allow_loop))
        return 1000 + len(self.created)

    def channel_set_position(self, stream: int, seconds: float) -> None:
        self.positions.append((stream, float(seconds)))

    def channel_play(self, stream: int, _restart: bool) -> None:
        self.played.append(stream)

    def channel_stop(self, _stream: int) -> None:
        return

    def stream_free(self, _stream: int) -> None:
        return

    def channel_remove_sync(self, _stream: int, _handle: int) -> None:
        return


class _DummyPlayer:
    def __init__(self) -> None:
        self._manager = _DummyManager()
        self._device_index = 0
        self._stream = 123
        self._device_context = _DummyContext()
        self._current_item_id = None
        self._start_offset = 0.0
        self._loop_start = None
        self._loop_end = None
        self._loop_active = False
        self._monitor_stop = Event()
        self._monitor_thread = None
        self._fade_thread = None
        self._loop_sync_handle = 0
        self._loop_sync_proc = None
        self._loop_alt_sync_handle = 0
        self._loop_alt_sync_proc = None
        self._loop_end_sync_handle = 0
        self._loop_end_sync_proc = None
        self._mix_sync_handle = 0
        self._mix_sync_proc = None
        self._mix_end_sync_handle = 0
        self._mix_end_sync_proc = None
        self.stopped = 0
        self.drop_called = 0

    def stop(self, *, _from_fade: bool = False) -> None:
        self.stopped += 1
        self._stream = 0

    def _apply_gain(self) -> None:
        return

    def _apply_loop_settings(self) -> None:
        return

    def _apply_mix_trigger(self, _mix_trigger_seconds, _on_mix_trigger) -> None:
        return

    def _start_monitor(self) -> None:
        return

    def _drop_preloaded(self) -> None:
        self.drop_called += 1


def test_bass_flow_play_uses_preloaded_stream_when_available(tmp_path):
    player = _DummyPlayer()
    prepared_ctx = _DummyContext()
    prepared_stream = 4242

    def _consume(path: Path, *, start_seconds: float, allow_loop: bool):
        assert path == tmp_path / "song.wav"
        assert start_seconds == 1.5
        assert allow_loop is True
        return prepared_stream, prepared_ctx

    player._consume_preloaded = _consume  # type: ignore[attr-defined]

    bass_flow.play(
        player,
        "item-1",
        str(tmp_path / "song.wav"),
        start_seconds=1.5,
        allow_loop=True,
        mix_trigger_seconds=None,
        on_mix_trigger=None,
    )

    assert player._manager.created == []
    assert player._stream == prepared_stream
    assert player._manager.played == [prepared_stream]
    assert player._manager.positions == [(prepared_stream, 1.5)]
    assert player.stopped == 1


def test_bass_flow_play_falls_back_to_stream_create(tmp_path):
    player = _DummyPlayer()

    def _consume(_path: Path, *, start_seconds: float, allow_loop: bool):
        return None

    player._consume_preloaded = _consume  # type: ignore[attr-defined]

    bass_flow.play(
        player,
        "item-1",
        str(tmp_path / "song.wav"),
        start_seconds=0.0,
        allow_loop=False,
        mix_trigger_seconds=None,
        on_mix_trigger=None,
    )

    assert len(player._manager.created) == 1
    assert player._manager.played == [player._stream]
    assert player.stopped == 1


def test_bass_flow_stop_drops_preloaded_only_on_manual_stop():
    player = _DummyPlayer()

    bass_flow.stop(player)
    assert player.drop_called == 1

    bass_flow.stop(player, _from_fade=True)
    assert player.drop_called == 1
