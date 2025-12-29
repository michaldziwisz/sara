from __future__ import annotations

import pytest


bass = pytest.importorskip("sara.audio.bass")


class _StubManager:
    def __init__(self) -> None:
        self.sync_calls: list[float] = []
        self.sync_end_calls: int = 0

    def channel_get_length_seconds(self, _stream: int) -> float:
        return 600.0

    def seconds_to_bytes(self, _stream: int, seconds: float) -> float:
        self.last_seconds = seconds
        return seconds

    def channel_set_sync_pos(self, _stream: int, position: float, proc, *, is_bytes: bool, mix_time: bool):
        # record target passed to BASS_ChannelSetSync
        self.sync_calls.append(position)
        self.last_pos_proc = proc
        self.last_is_bytes = is_bytes
        self.last_mix_time = mix_time
        return 123

    def channel_set_sync_end(self, _stream: int, proc):
        self.sync_end_calls += 1
        self.last_end_proc = proc
        return 456

    def channel_remove_sync(self, _stream: int, _handle: int) -> None:  # pragma: no cover - not needed in tests
        return None

    def make_sync_proc(self, func):
        return func


def _player_with_stream(offset: float) -> tuple[bass.BassPlayer, _StubManager]:
    manager = _StubManager()
    player = bass.BassPlayer(manager, 0)
    player._stream = 1  # bypass actual BASS stream creation
    player._start_offset = offset
    return player, manager


def test_bass_mix_trigger_offsets_start_position():
    player, manager = _player_with_stream(1.7)
    player._apply_mix_trigger(256.463, lambda: None)
    assert manager.sync_calls[-1] == pytest.approx(254.763)
    assert manager.sync_end_calls == 1
    assert manager.last_mix_time is True


def test_bass_mix_trigger_without_offset_unchanged():
    player, manager = _player_with_stream(0.0)
    player._apply_mix_trigger(12.5, lambda: None)
    assert manager.sync_calls[-1] == pytest.approx(12.5)
    assert manager.sync_end_calls == 1
    assert manager.last_mix_time is True


def test_bass_mix_trigger_fires_once_for_pos_and_end():
    player, manager = _player_with_stream(0.0)
    fired = {"count": 0}

    def _cb():
        fired["count"] += 1

    player._apply_mix_trigger(12.5, _cb)
    assert manager.sync_end_calls == 1
    assert fired["count"] == 0

    manager.last_pos_proc(0, player._stream, 0, None)
    manager.last_end_proc(0, player._stream, 0, None)
    assert fired["count"] == 1
