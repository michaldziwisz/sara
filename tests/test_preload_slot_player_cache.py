from __future__ import annotations

from types import SimpleNamespace

from sara.audio.types import AudioDevice, BackendType
from sara.core.playlist import PlaylistItem, PlaylistKind, PlaylistModel
from sara.ui.playback.controller import PlaybackController


class _DummyPlayer:
    def __init__(self, label: str) -> None:
        self.label = label
        self.preload_calls: list[tuple[str, float, bool]] = []
        self.play_calls: list[tuple[str, str]] = []

    def supports_mix_trigger(self) -> bool:
        return False

    def set_finished_callback(self, _callback) -> None:
        return None

    def set_progress_callback(self, _callback) -> None:
        return None

    def set_gain_db(self, _gain_db) -> None:
        return None

    def set_loop(self, _start_seconds, _end_seconds) -> None:
        return None

    def fade_out(self, _duration: float) -> None:
        return None

    def stop(self) -> None:
        return None

    def preload(self, source_path: str, *, start_seconds: float = 0.0, allow_loop: bool = False) -> bool:
        self.preload_calls.append((source_path, float(start_seconds), bool(allow_loop)))
        return True

    def play(
        self,
        playlist_item_id: str,
        source_path: str,
        *,
        start_seconds: float = 0.0,
        allow_loop: bool = False,
        mix_trigger_seconds=None,
        on_mix_trigger=None,
    ):
        self.play_calls.append((playlist_item_id, source_path))
        return None


class _DummyAudioEngine:
    def __init__(self) -> None:
        self._devices = [AudioDevice(id="dev-1", name="dev-1", backend=BackendType.BASS)]
        self.created_players: list[_DummyPlayer] = []

    def stop_all(self) -> None:
        return None

    def get_devices(self):
        return list(self._devices)

    def refresh_devices(self) -> None:
        return None

    def create_player_instance(self, device_id: str):
        assert device_id == "dev-1"
        player = _DummyPlayer(label=f"player-{len(self.created_players)}")
        self.created_players.append(player)
        return player


def test_schedule_next_preload_targets_next_slot_player(tmp_path) -> None:
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    playlist.set_output_slots(["dev-1", "dev-1"])

    path_a = tmp_path / "a.wav"
    path_a.write_text("a")
    path_b = tmp_path / "b.wav"
    path_b.write_text("b")

    item_a = PlaylistItem(id="a", path=path_a, title="A", duration_seconds=10.0, cue_in_seconds=0.0)
    item_b = PlaylistItem(id="b", path=path_b, title="B", duration_seconds=12.0, cue_in_seconds=1.25)
    playlist.add_items([item_a, item_b])

    engine = _DummyAudioEngine()
    settings = SimpleNamespace(get_pfl_device=lambda: None, get_alternate_play_next=lambda: False)
    controller = PlaybackController(engine, settings, lambda *_args: None)

    controller.start_item(
        playlist,
        item_a,
        start_seconds=0.0,
        on_finished=lambda _id: None,
        on_progress=lambda _id, _sec: None,
        restart_if_playing=False,
        mix_trigger_seconds=None,
        on_mix_trigger=None,
    )
    assert len(engine.created_players) == 1, "slot #1 should allocate one player"

    controller.schedule_next_preload(playlist, current_item_id=item_a.id)
    executor = controller._preload_executor
    assert executor is not None
    executor.shutdown(wait=True)
    controller._preload_executor = None

    assert len(engine.created_players) == 2, "preload should allocate player for slot #2"
    slot2_player = engine.created_players[1]
    assert slot2_player.preload_calls == [(str(path_b), 1.25, False)]

    controller.start_item(
        playlist,
        item_b,
        start_seconds=item_b.cue_in_seconds or 0.0,
        on_finished=lambda _id: None,
        on_progress=lambda _id, _sec: None,
        restart_if_playing=False,
        mix_trigger_seconds=None,
        on_mix_trigger=None,
    )
    assert len(engine.created_players) == 2, "start should reuse cached slot #2 player"
    assert slot2_player.play_calls and slot2_player.play_calls[-1] == ("b", str(path_b))

