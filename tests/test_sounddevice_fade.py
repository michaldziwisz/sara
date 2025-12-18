from threading import Event

from sara.audio.engine import AudioDevice, BackendType, SoundDevicePlayer
import sara.audio.sounddevice_player as sd_player


def test_sounddevice_player_fade_out_reduces_gain(monkeypatch):
    monkeypatch.setattr(sd_player, "sd", object())
    monkeypatch.setattr(sd_player, "sf", object())

    device = AudioDevice(id="wasapi:1", name="Dummy", backend=BackendType.WASAPI, raw_index=0)
    player = SoundDevicePlayer(device)

    class DummyThread:
        def __init__(self) -> None:
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout: float | None = None) -> None:
            self._alive = False

    player._thread = DummyThread()
    player._stop_event = Event()
    finished_event = Event()
    player._finished_event = finished_event
    player._current_item = "item-id"
    player._gain_factor = 1.0

    player.fade_out(0.02)

    assert finished_event.wait(timeout=1.0)
    assert player._current_item is None
    assert player._stop_event is None
    assert player._gain_factor == 0.0
