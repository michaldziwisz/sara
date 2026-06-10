from __future__ import annotations

import pytest


bass = pytest.importorskip("sara.audio.bass")


class _StubManager:
    def __init__(self) -> None:
        self.sync_calls: list[float] = []
        self.sync_mix_times: list[bool] = []
        self.sync_end_calls: int = 0
        self.removed_syncs: list[int] = []
        self.byte_positions: list[tuple[int, int]] = []
        self.current_byte_position: int = 0

    def channel_get_length_seconds(self, _stream: int) -> float:
        return 600.0

    def seconds_to_bytes(self, _stream: int, seconds: float) -> float:
        self.last_seconds = seconds
        return int(round(seconds * 1000))

    def channel_set_sync_pos(self, _stream: int, position: float, proc, *, is_bytes: bool, mix_time: bool):
        # record target passed to BASS_ChannelSetSync
        self.sync_calls.append(position)
        self.sync_mix_times.append(mix_time)
        self.last_pos_proc = proc
        self.last_is_bytes = is_bytes
        self.last_mix_time = mix_time
        return 100 + len(self.sync_calls)

    def channel_set_sync_end(self, _stream: int, proc):
        self.sync_end_calls += 1
        self.last_end_proc = proc
        return 456

    def channel_remove_sync(self, _stream: int, handle: int) -> None:
        self.removed_syncs.append(handle)

    def channel_set_position_bytes(self, stream: int, byte_pos: int) -> None:
        self.byte_positions.append((stream, byte_pos))
        self.current_byte_position = byte_pos

    def channel_get_seconds(self, _stream: int) -> float:
        return self.current_byte_position / 1000.0

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
    assert manager.sync_calls[-1] == pytest.approx(254763)
    assert manager.sync_end_calls == 1
    assert manager.last_mix_time is True


def test_bass_mix_trigger_without_offset_unchanged():
    player, manager = _player_with_stream(0.0)
    player._apply_mix_trigger(12.5, lambda: None)
    assert manager.sync_calls[-1] == pytest.approx(12500)
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


def test_bass_loop_sets_marker_syncs_and_jumps_to_loop_start():
    player, manager = _player_with_stream(0.0)

    player.set_loop(26.137, 34.335)

    assert player._loop_active is True
    assert player._loop_start_bytes == 26137
    assert player._loop_end_bytes == 34335
    assert manager.sync_calls[-1:] == [34335]
    assert manager.sync_mix_times[-1:] == [True]

    manager.last_pos_proc(0, player._stream, 0, None)

    assert manager.byte_positions[-1] == (player._stream, 26137)
    assert player._loop_iteration == 1


def test_bass_loop_clear_removes_marker_syncs():
    player, manager = _player_with_stream(0.0)
    player.set_loop(26.137, 34.335)

    player.set_loop(None, None)

    assert player._loop_active is False
    assert manager.removed_syncs[-1:] == [101]
