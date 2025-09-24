from typing import List

from sara.audio.engine import AudioDevice, AudioEngine, BackendProvider, BackendType, Player


class DummyPlayer:
    def __init__(self) -> None:
        self.stopped = False
        self.finished_cleared = False
        self.progress_cleared = False
        self.gain_db = None

    def play(self, playlist_item_id: str, source_path: str, *, start_seconds: float = 0.0):  # pragma: no cover
        return None

    def pause(self) -> None:  # pragma: no cover
        pass

    def stop(self) -> None:
        self.stopped = True

    def fade_out(self, duration: float) -> None:  # pragma: no cover
        pass

    def set_finished_callback(self, callback):
        if callback is None:
            self.finished_cleared = True

    def set_progress_callback(self, callback):
        if callback is None:
            self.progress_cleared = True

    def set_gain_db(self, gain_db):
        self.gain_db = gain_db

    def set_loop(self, start_seconds, end_seconds):  # pragma: no cover
        return None


class DummyProvider:
    backend = BackendType.WASAPI

    def __init__(self, player: Player, device: AudioDevice) -> None:
        self._player = player
        self._device = device

    def list_devices(self) -> List[AudioDevice]:
        return [self._device]

    def create_player(self, device: AudioDevice) -> Player:
        return self._player


def test_audio_engine_stop_all_clears_callbacks():
    device = AudioDevice(id="dummy:1", name="Dummy", backend=BackendType.WASAPI)
    dummy_player = DummyPlayer()
    dummy_provider = DummyProvider(dummy_player, device)

    engine = AudioEngine()
    engine._providers = [dummy_provider]  # type: ignore[attr-defined]
    engine.refresh_devices()

    player = engine.create_player(device.id)
    assert player is dummy_player

    engine.stop_all()

    assert dummy_player.stopped is True
    assert dummy_player.finished_cleared is True
    assert dummy_player.progress_cleared is True
