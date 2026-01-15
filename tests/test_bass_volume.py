from __future__ import annotations

from types import SimpleNamespace

from sara.audio.bass._manager import streams as streams_mod
from sara.audio.bass.native import _BassConstants


class _DummyLib:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, float]] = []

    def BASS_ChannelSetAttribute(self, stream: int, attrib: int, value) -> bool:  # noqa: ANN001 - ctypes float
        self.calls.append((int(stream), int(attrib), float(value.value)))
        return True


def test_bass_channel_set_volume_allows_amplification() -> None:
    manager = SimpleNamespace(_lib=_DummyLib())
    streams_mod.channel_set_volume(manager, 123, 7.5)
    assert manager._lib.calls == [(123, _BassConstants.ATTRIB_VOL, 7.5)]


def test_bass_channel_set_volume_clamps_negative_to_zero() -> None:
    manager = SimpleNamespace(_lib=_DummyLib())
    streams_mod.channel_set_volume(manager, 123, -2.0)
    assert manager._lib.calls == [(123, _BassConstants.ATTRIB_VOL, 0.0)]

