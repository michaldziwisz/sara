"""Testy charakteryzujące: wyzwalacz miksu odpala dokładnie raz.

Zafiksowanie kontraktu zanim refaktor (Faza 1-4) cokolwiek ruszy. Wyzwalacz
miksu w BASS korzysta z dwóch synców (SYNC_POS w mixtime + SYNC_END jako
fallback). Niezależnie od kolejności, w jakiej BASS wywoła oba callbacki,
nasz callback użytkownika MUSI odpalić dokładnie raz.
"""

from __future__ import annotations

import pytest


bass = pytest.importorskip("sara.audio.bass")


class _StubManager:
    """Minimalny stub managera BASS — wzorowany na tests/test_bass_player.py."""

    def __init__(self) -> None:
        self.sync_calls: list[float] = []
        self.sync_end_calls: int = 0

    def channel_get_length_seconds(self, _stream: int) -> float:
        return 600.0

    def seconds_to_bytes(self, _stream: int, seconds: float) -> int:
        return int(round(seconds * 1000))

    def channel_get_seconds(self, _stream: int) -> float:
        return 0.0

    def channel_set_sync_pos(self, _stream, position, proc, *, is_bytes, mix_time):
        self.sync_calls.append(position)
        self.last_pos_proc = proc
        return 100 + len(self.sync_calls)

    def channel_set_sync_end(self, _stream, proc):
        self.sync_end_calls += 1
        self.last_end_proc = proc
        return 456

    def channel_remove_sync(self, _stream, _handle) -> None:
        return None

    def make_sync_proc(self, func):
        return func


def _player_with_stream(offset: float = 0.0):
    manager = _StubManager()
    player = bass.BassPlayer(manager, 0)
    player._stream = 1
    player._start_offset = offset
    return player, manager


def test_mix_trigger_fires_once_pos_then_end():
    player, manager = _player_with_stream()
    fired = {"count": 0}
    player._apply_mix_trigger(12.5, lambda: fired.__setitem__("count", fired["count"] + 1))

    manager.last_pos_proc(0, player._stream, 0, None)
    manager.last_end_proc(0, player._stream, 0, None)

    assert fired["count"] == 1


def test_mix_trigger_fires_once_end_then_pos():
    """Odwrotna kolejność: SYNC_END przed SYNC_POS — wciąż dokładnie raz."""
    player, manager = _player_with_stream()
    fired = {"count": 0}
    player._apply_mix_trigger(12.5, lambda: fired.__setitem__("count", fired["count"] + 1))

    manager.last_end_proc(0, player._stream, 0, None)
    manager.last_pos_proc(0, player._stream, 0, None)

    assert fired["count"] == 1


def test_mix_trigger_fires_once_double_pos():
    """Podwójne wywołanie tego samego synca nie może odpalić dwa razy."""
    player, manager = _player_with_stream()
    fired = {"count": 0}
    player._apply_mix_trigger(12.5, lambda: fired.__setitem__("count", fired["count"] + 1))

    manager.last_pos_proc(0, player._stream, 0, None)
    manager.last_pos_proc(0, player._stream, 0, None)

    assert fired["count"] == 1


def test_mix_trigger_offset_subtracted_once():
    """start_offset odejmowany dokładnie raz przy konwersji na bajty."""
    player, manager = _player_with_stream(offset=1.7)
    player._apply_mix_trigger(256.463, lambda: None)
    # (256.463 - 1.7) * 1000 = 254763
    assert manager.sync_calls[-1] == pytest.approx(254763)
    assert manager.sync_end_calls == 1
