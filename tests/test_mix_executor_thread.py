from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sara.core.mix_planner import mark_mix_triggered, register_mix_plan, resolve_mix_timing
from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistKind, PlaylistModel
from sara.ui.auto_mix_tracker import AutoMixTracker
from sara.ui.mix_runtime.thread_executor import handle_native_mix_trigger


class _DummyPlayer:
    def __init__(self) -> None:
        self.fade_calls: list[float] = []

    def fade_out(self, duration: float) -> None:
        self.fade_calls.append(float(duration))

    def supports_mix_trigger(self) -> bool:
        return True


class _DummyPlayback:
    def __init__(self) -> None:
        self.contexts: dict[tuple[str, str], object] = {}
        self.auto_mix_state: dict[tuple[str, str], object] = {}
        self.started: list[dict] = []
        self.updated: list[tuple[str, str, float | None]] = []

    def start_item(
        self,
        playlist: PlaylistModel,
        item: PlaylistItem,
        *,
        start_seconds: float,
        on_finished,
        on_progress,
        restart_if_playing: bool = False,
        mix_trigger_seconds: float | None = None,
        on_mix_trigger=None,
    ):
        player = _DummyPlayer()
        ctx = SimpleNamespace(player=player, device_id="dev-1", slot_index=0)
        self.contexts[(playlist.id, item.id)] = ctx
        self.started.append(
            {
                "playlist_id": playlist.id,
                "item_id": item.id,
                "start_seconds": float(start_seconds),
                "restart_if_playing": bool(restart_if_playing),
                "mix_trigger_seconds": mix_trigger_seconds,
                "has_on_mix_trigger": callable(on_mix_trigger),
            }
        )
        return ctx

    def update_mix_trigger(
        self,
        playlist_id: str,
        item_id: str,
        *,
        mix_trigger_seconds: float | None,
        on_mix_trigger=None,
    ) -> bool:
        self.updated.append((str(playlist_id), str(item_id), mix_trigger_seconds))
        return True

    def schedule_next_preload(self, *_args, **_kwargs) -> None:
        return None


class _DummyFrame:
    def __init__(self, playlist: PlaylistModel, *, fade: float = 2.0) -> None:
        self._playlist = playlist
        self._fade_duration = float(fade)
        self._mix_plans: dict[tuple[str, str], object] = {}
        self._mix_trigger_points: dict[tuple[str, str], float] = {}
        self._active_break_item: dict[str, str] = {}
        self._auto_mix_enabled = True
        self._playback = _DummyPlayback()
        self._auto_mix_tracker = AutoMixTracker()
        self._auto_mix_busy: dict[str, bool] = {}
        self._last_started_item_id: dict[str, str | None] = {}
        self._focus_lock: dict[str, bool] = {}
        self._focus_playing_track = False

    def _get_playlist_model(self, playlist_id: str) -> PlaylistModel | None:
        return self._playlist if self._playlist.id == playlist_id else None

    def _playlist_has_selection(self, playlist_id: str) -> bool:
        playlist = self._get_playlist_model(playlist_id)
        return bool(playlist and any(item.is_selected for item in playlist.items))

    def _supports_mix_trigger(self, _player=None) -> bool:
        return True

    def _register_mix_plan(
        self,
        playlist_id: str,
        item_id: str,
        *,
        mix_at: float | None,
        fade_seconds: float,
        base_cue: float,
        effective_duration: float,
        native_trigger: bool,
    ) -> None:
        register_mix_plan(
            self._mix_plans,
            self._mix_trigger_points,
            playlist_id,
            item_id,
            mix_at=mix_at,
            fade_seconds=fade_seconds,
            base_cue=base_cue,
            effective_duration=effective_duration,
            native_trigger=native_trigger,
        )

    def _mark_mix_triggered(self, playlist_id: str, item_id: str) -> None:
        mark_mix_triggered(self._mix_plans, playlist_id, item_id)

    def _resolve_mix_timing(
        self,
        item: PlaylistItem,
        overrides: dict[str, float | None] | None = None,
        *,
        effective_duration_override: float | None = None,
    ) -> tuple[float | None, float, float, float]:
        return resolve_mix_timing(
            item,
            self._fade_duration,
            overrides,
            effective_duration_override=effective_duration_override,
        )

    def _get_playback_context(self, playlist_id: str):
        for key, ctx in reversed(list(self._playback.contexts.items())):
            if key[0] == playlist_id:
                return key, ctx
        return None

    def _handle_playback_progress(self, *_args, **_kwargs) -> None:
        return None

    def _handle_playback_finished(self, *_args, **_kwargs) -> None:
        return None

    def _announce_event(self, *_args, **_kwargs) -> None:
        return None

    def _refresh_selection_display(self, *_args, **_kwargs) -> None:
        return None


def test_thread_executor_starts_next_and_fades_current(tmp_path: Path) -> None:
    path_a = tmp_path / "a.mp3"
    path_b = tmp_path / "b.mp3"
    path_a.write_text("a")
    path_b.write_text("b")

    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    current = PlaylistItem(id="a", path=path_a, title="A", duration_seconds=10.0, segue_seconds=4.0)
    next_item = PlaylistItem(id="b", path=path_b, title="B", duration_seconds=8.0)
    playlist.add_items([current, next_item])

    current.status = PlaylistItemStatus.PLAYING
    current.current_position = 4.0

    frame = _DummyFrame(playlist, fade=2.0)
    current_player = _DummyPlayer()
    frame._playback.contexts[(playlist.id, current.id)] = SimpleNamespace(player=current_player, device_id="dev-1", slot_index=0)

    frame._register_mix_plan(
        playlist.id,
        current.id,
        mix_at=4.0,
        fade_seconds=2.0,
        base_cue=0.0,
        effective_duration=10.0,
        native_trigger=True,
    )

    enqueued: list[tuple[str, str]] = []
    handle_native_mix_trigger(
        frame,
        playlist_id=playlist.id,
        item_id=current.id,
        enqueue_mix_trigger=lambda pl_id, it_id: enqueued.append((pl_id, it_id)),
    )

    assert frame._playback.started and frame._playback.started[0]["item_id"] == "b"
    assert next_item.status is PlaylistItemStatus.PLAYING
    assert current_player.fade_calls == [2.0]
    assert frame._last_started_item_id[playlist.id] == "b"
    assert (playlist.id, next_item.id) in frame._mix_plans
    assert frame._playback.started[0]["has_on_mix_trigger"] is True

