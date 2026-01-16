from __future__ import annotations

from types import SimpleNamespace

from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistKind, PlaylistModel
from sara.ui.playback.start_item import start_item_impl


class _DummyPlayer:
    def __init__(self) -> None:
        self.play_calls: list[dict[str, object]] = []

    def stop(self) -> None:
        return None

    def is_playing(self) -> bool:
        return False

    def play(
        self,
        playlist_item_id: str,
        source_path: str,
        *,
        start_seconds: float = 0.0,
        allow_loop: bool = True,
        mix_trigger_seconds=None,
        on_mix_trigger=None,
    ):
        self.play_calls.append(
            {
                "id": playlist_item_id,
                "path": source_path,
                "start_seconds": float(start_seconds),
                "allow_loop": bool(allow_loop),
                "mix_trigger_seconds": mix_trigger_seconds,
                "on_mix_trigger": on_mix_trigger,
            }
        )
        return None

    def pause(self) -> None:
        return None

    def fade_out(self, _duration: float) -> None:
        return None

    def set_finished_callback(self, _callback) -> None:
        return None

    def set_progress_callback(self, _callback) -> None:
        return None

    def set_mix_trigger(self, _mix_trigger_seconds, _on_mix_trigger) -> None:
        return None

    def set_gain_db(self, _gain_db) -> None:
        return None

    def set_loop(self, _start_seconds, _end_seconds) -> None:
        return None

    def supports_mix_trigger(self) -> bool:
        return False


def test_start_item_resets_stale_progress_when_restart_played(tmp_path) -> None:
    player = _DummyPlayer()

    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-1",
        path=tmp_path / "a.wav",
        title="A",
        duration_seconds=100.0,
        cue_in_seconds=10.0,
    )
    item.path.write_text("a")
    item.status = PlaylistItemStatus.PLAYED
    item.current_position = item.duration_seconds

    controller = SimpleNamespace(
        _settings=SimpleNamespace(get_alternate_play_next=lambda: False),
        _announce=lambda *_a, **_k: None,
        _playback_contexts={},
        _auto_mix_state={},
        get_busy_device_ids=lambda: set(),
        supports_mix_trigger=lambda _p: False,
        _ensure_player=lambda _playlist: (player, "dev-1", 0),
    )

    ctx = start_item_impl(
        controller,
        playlist,
        item,
        start_seconds=item.cue_in_seconds or 0.0,
        on_finished=lambda _id: None,
        on_progress=lambda _id, _sec: None,
        restart_if_playing=True,
        mix_trigger_seconds=None,
        on_mix_trigger=None,
    )

    assert ctx is not None
    assert item.status is PlaylistItemStatus.PENDING
    assert item.current_position == 0.0


def test_start_item_sets_progress_for_nonzero_start(tmp_path) -> None:
    player = _DummyPlayer()
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-1",
        path=tmp_path / "a.wav",
        title="A",
        duration_seconds=100.0,
        cue_in_seconds=10.0,
    )
    item.path.write_text("a")
    item.status = PlaylistItemStatus.PENDING
    item.current_position = 0.0

    controller = SimpleNamespace(
        _settings=SimpleNamespace(get_alternate_play_next=lambda: False),
        _announce=lambda *_a, **_k: None,
        _playback_contexts={},
        _auto_mix_state={},
        get_busy_device_ids=lambda: set(),
        supports_mix_trigger=lambda _p: False,
        _ensure_player=lambda _playlist: (player, "dev-1", 0),
    )

    start_seconds = 25.0
    ctx = start_item_impl(
        controller,
        playlist,
        item,
        start_seconds=start_seconds,
        on_finished=lambda _id: None,
        on_progress=lambda _id, _sec: None,
        restart_if_playing=False,
        mix_trigger_seconds=None,
        on_mix_trigger=None,
    )

    assert ctx is not None
    assert item.current_position == start_seconds - (item.cue_in_seconds or 0.0)

