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
        self.looping_calls: list[tuple[int, bool]] = []
        self.loop_point_calls: list[tuple[int, int, int]] = []
        self.cleared_loop_points: list[int] = []
        self.native_loop_supported: bool = True

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

    def channel_set_looping(self, stream: int, enabled: bool) -> None:
        self.looping_calls.append((stream, enabled))

    def channel_set_loop_points(self, stream: int, start_byte: int, end_byte: int) -> None:
        if not self.native_loop_supported:
            raise RuntimeError("native loop unavailable")
        self.loop_point_calls.append((stream, start_byte, end_byte))

    def channel_clear_loop_points(self, stream: int) -> None:
        self.cleared_loop_points.append(stream)

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


def test_bass_loop_uses_native_loop_points():
    player, manager = _player_with_stream(0.0)

    player.set_loop(26.137, 34.335)

    assert player._loop_active is True
    assert player._loop_start_bytes == 26137
    assert player._loop_end_bytes == 34335
    assert player._loop_native_active is True
    assert manager.looping_calls[-1:] == [(player._stream, True)]
    assert manager.loop_point_calls[-1:] == [(player._stream, 26137, 34335)]
    assert manager.sync_calls == []


def test_bass_loop_falls_back_to_marker_syncs_and_jumps_to_loop_start():
    player, manager = _player_with_stream(0.0)
    manager.native_loop_supported = False

    player.set_loop(26.137, 34.335)

    assert player._loop_native_active is False
    assert manager.looping_calls[-2:] == [(player._stream, True), (player._stream, False)]
    assert manager.sync_calls[-1:] == [34335]
    assert manager.sync_mix_times[-1:] == [True]

    manager.last_pos_proc(0, player._stream, 0, None)

    assert manager.byte_positions[-1] == (player._stream, 26137)
    assert player._loop_iteration == 1


def test_bass_loop_enable_after_end_jumps_immediately():
    player, manager = _player_with_stream(0.0)
    manager.current_byte_position = 40000

    player.set_loop(26.137, 34.335)

    assert manager.loop_point_calls[-1:] == [(player._stream, 26137, 34335)]
    assert manager.byte_positions[-1] == (player._stream, 26137)
    assert player._loop_iteration == 1


def test_bass_loop_clear_disables_native_looping():
    player, manager = _player_with_stream(0.0)
    player.set_loop(26.137, 34.335)

    player.set_loop(None, None)

    assert player._loop_active is False
    assert player._loop_native_active is False
    assert manager.cleared_loop_points[-1:] == [player._stream]
    assert manager.looping_calls[-1:] == [(player._stream, False)]


def test_bass_loop_clear_removes_marker_syncs():
    player, manager = _player_with_stream(0.0)
    manager.native_loop_supported = False
    player.set_loop(26.137, 34.335)

    player.set_loop(None, None)

    assert player._loop_active is False
    assert manager.removed_syncs[-1:] == [101]


def test_bass_set_debug_loop_updates_concrete_player_module():
    import sara.audio.bass.player_base as compat_player_base_mod
    import sara.audio.bass_player_base as legacy_player_base_mod
    from sara.audio.bass.player import base as player_base_mod

    old_package_debug = bass._DEBUG_LOOP
    old_player_debug = player_base_mod._DEBUG_LOOP
    old_compat_debug = compat_player_base_mod._DEBUG_LOOP
    old_legacy_debug = legacy_player_base_mod._DEBUG_LOOP
    try:
        bass.set_debug_loop(True)

        assert bass._DEBUG_LOOP is True
        assert player_base_mod._DEBUG_LOOP is True
        assert compat_player_base_mod._DEBUG_LOOP is True
        assert legacy_player_base_mod._DEBUG_LOOP is True
        assert bass.BassPlayer(_StubManager(), 0)._debug_loop is True

        bass.set_debug_loop(False)

        assert bass._DEBUG_LOOP is False
        assert player_base_mod._DEBUG_LOOP is False
        assert compat_player_base_mod._DEBUG_LOOP is False
        assert legacy_player_base_mod._DEBUG_LOOP is False
        assert bass.BassPlayer(_StubManager(), 0)._debug_loop is False
    finally:
        bass._DEBUG_LOOP = old_package_debug
        player_base_mod._DEBUG_LOOP = old_player_debug
        compat_player_base_mod._DEBUG_LOOP = old_compat_debug
        legacy_player_base_mod._DEBUG_LOOP = old_legacy_debug
