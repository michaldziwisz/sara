import time
from threading import Event

from sara.audio.engine import MockPlayer, AudioDevice, BackendType


def test_mock_player_progress_and_finish_callbacks():
    device = AudioDevice(id="mock:1", name="Mock Device", backend=BackendType.WASAPI)
    player = MockPlayer(device)
    player.set_gain_db(-5.0)

    progress_events: list[float] = []
    finished = Event()

    def on_progress(item_id: str, seconds: float) -> None:
        progress_events.append(seconds)

    def on_finished(item_id: str) -> None:
        finished.set()

    player.set_progress_callback(on_progress)
    player.set_finished_callback(on_finished)

    player.play("item", "path")

    assert finished.wait(1.5)
    assert progress_events, "Progress callback should be invoked"
    assert progress_events[-1] >= 0.1

    player.stop()


def test_mock_player_loop_keeps_running():
    device = AudioDevice(id="mock:2", name="Mock Device", backend=BackendType.WASAPI)
    player = MockPlayer(device)

    finished = Event()

    player.set_finished_callback(lambda _: finished.set())
    player.set_progress_callback(lambda _id, _sec: None)

    player.set_loop(0.2, 0.4)
    player.play("item", "path", start_seconds=0.2)

    assert not finished.wait(1.0), "Looping playback should not finish quickly"

    player.stop()
