from __future__ import annotations

from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Callable, Optional

import pytest

wx = pytest.importorskip("wx")  # noqa: F401

from sara.core.app_state import AppState
from sara.core.mix_planner import MixPlan
from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistKind, PlaylistModel
from sara.ui.auto_mix_tracker import AutoMixTracker
from sara.ui.main_frame import MainFrame


class _DummyPlayer:
    def __init__(self, device_id: str, supports: bool = True):
        self.device_id = device_id
        self._supports = supports
        self.play_calls: list[dict] = []
        self.mix_calls: list[tuple[Optional[float], Optional[Callable]]] = []
        self.finished_callback: Optional[Callable[[str], None]] = None
        self.progress_callback: Optional[Callable[[str, float], None]] = None

    def supports_mix_trigger(self) -> bool:
        return self._supports

    def play(
        self,
        playlist_item_id: str,
        source_path: str,
        *,
        start_seconds: float = 0.0,
        allow_loop: bool = False,
        mix_trigger_seconds: float | None = None,
        on_mix_trigger: Callable[[], None] | None = None,
    ) -> Event:
        self.play_calls.append(
            {
                "item_id": playlist_item_id,
                "path": source_path,
                "start_seconds": start_seconds,
                "mix_trigger_seconds": mix_trigger_seconds,
                "on_mix_trigger": on_mix_trigger,
                "allow_loop": allow_loop,
            }
        )
        return Event()

    def set_finished_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        self.finished_callback = callback

    def set_progress_callback(self, callback: Optional[Callable[[str, float], None]]) -> None:
        self.progress_callback = callback

    def set_gain_db(self, _gain_db):
        return None

    def set_loop(self, _start_seconds, _end_seconds):
        return None

    def stop(self):
        return None

    def fade_out(self, _duration: float):
        return None

    def set_mix_trigger(self, mix_trigger_seconds: Optional[float], on_mix_trigger: Optional[Callable[[], None]]):
        self.mix_calls.append((mix_trigger_seconds, on_mix_trigger))


def _register_playlist(frame: MainFrame, playlist: PlaylistModel, panel: object | None = None) -> None:
    if not hasattr(frame, "_state"):
        frame._state = AppState()
    frame._state.add_playlist(playlist)
    if not hasattr(frame, "_playlists"):
        frame._playlists = {}
    if panel is not None:
        frame._playlists[playlist.id] = panel  # type: ignore[attr-defined]


def test_undo_like_remove_clears_mix_state(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._mix_plans = {("pl-1", "item-1"): None}
    frame._mix_trigger_points = {("pl-1", "item-1"): 5.0}
    frame._playback = SimpleNamespace(
        contexts={(("pl-1", "item-1")): SimpleNamespace(player=None)},
        clear_auto_mix=lambda: None,
        stop_playlist=lambda _pl_id, fade_duration=0.0: [(("pl-1", "item-1"), None)],
    )
    model = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(id="item-1", path=tmp_path / "a", title="A", duration_seconds=1.0)
    model.items = [item]
    dummy_panel = SimpleNamespace(
        model=model,
        mark_item_status=lambda *_args, **_kwargs: None,
        update_progress=lambda *_args, **_kwargs: None,
        refresh=lambda *_args, **_kwargs: None,
    )
    frame._playlists = {"pl-1": dummy_panel}
    frame._cleanup_unused_mixers = lambda: None
    frame._active_break_item = {}
    frame._announce_event = lambda *args, **kwargs: None
    frame._remove_item_from_playlist = lambda _panel, _model, idx, refocus=True: _model.items.pop(idx)
    frame._stop_playlist_playback("pl-1", mark_played=False, fade_duration=0.0)
    assert ("pl-1", "item-1") not in frame._mix_trigger_points
    assert ("pl-1", "item-1") not in frame._mix_plans


def test_manual_play_request_stops_loop_hold_without_automix(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._auto_mix_enabled = False
    frame._fade_duration = 2.0
    frame._mix_plans = {}
    frame._mix_trigger_points = {}
    frame._active_break_item = {}
    frame._stop_preview = lambda: None
    frame._supports_mix_trigger = lambda _p: False
    frame._resolve_mix_timing = lambda itm, overrides=None, effective_duration_override=None: (
        None,
        frame._fade_duration,
        itm.cue_in_seconds or 0.0,
        itm.effective_duration_seconds,
    )

    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    path_a = tmp_path / "a.wav"
    path_b = tmp_path / "b.wav"
    path_a.write_text("dummy")
    path_b.write_text("dummy")
    looping = PlaylistItem(
        id="looping",
        path=path_a,
        title="Looping",
        duration_seconds=10.0,
        loop_start_seconds=1.0,
        loop_end_seconds=3.0,
        loop_enabled=True,
        status=PlaylistItemStatus.PLAYING,
    )
    next_item = PlaylistItem(
        id="next",
        path=path_b,
        title="Next",
        duration_seconds=10.0,
    )
    playlist.add_items([looping, next_item])

    class _Panel:
        def __init__(self, model):
            self.model = model

        def mark_item_status(self, *_a, **_k):
            return None

        def refresh(self, *_a, **_k):
            return None

        def get_selected_indices(self):
            return []

        def get_focused_index(self):
            return -1

        def select_index(self, *_a, **_k):
            return None

    panel = _Panel(playlist)

    existing_key = (playlist.id, looping.id)
    stop_calls: list[tuple] = []
    frame._stop_playlist_playback = lambda pid, *, mark_played, fade_duration=0.0: stop_calls.append(
        (pid, mark_played, fade_duration)
    )

    def _start_item(*_a, **_k):
        raise RuntimeError("abort after stop check")

    frame._playback = SimpleNamespace(
        contexts={existing_key: SimpleNamespace(player=_DummyPlayer("dev-1"), device_id="dev-1", slot_index=0)},
        auto_mix_state={existing_key: "loop_hold"},
        get_context=lambda _pid: (existing_key, frame._playback.contexts[existing_key]),
        start_item=_start_item,
    )

    assert frame._start_playback(panel, next_item, restart_playing=True) is False
    assert stop_calls == [(playlist.id, True, frame._fade_duration)]


def test_start_next_clears_queued_selection_even_when_follow_disabled(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._auto_mix_enabled = False
    frame._focus_playing_track = False
    frame._fade_duration = 0.0
    frame._last_started_item_id = {}
    frame._auto_mix_tracker = SimpleNamespace(set_last_started=lambda *_a, **_k: None)
    frame._format_track_name = lambda item: item.title
    frame._announce_event = lambda *_a, **_k: None
    frame._start_playback = lambda *_a, **_k: True
    frame._playback = SimpleNamespace(get_context=lambda *_a, **_k: None)

    refreshed: list[str] = []
    frame._refresh_selection_display = lambda playlist_id: refreshed.append(playlist_id)

    path_a = tmp_path / "a.wav"
    path_a.write_text("dummy")
    item = PlaylistItem(id="a", path=path_a, title="A", duration_seconds=1.0)
    item.is_selected = True
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    playlist.add_items([item])

    panel = SimpleNamespace(model=playlist, get_selected_indices=lambda: [], get_focused_index=lambda: -1)

    assert frame._start_next_from_playlist(panel, ignore_ui_selection=False, advance_focus=False) is True
    assert playlist.items[0].is_selected is False
    assert refreshed == ["pl-1"]


def test_manual_finish_starts_next_when_queue_remains(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._auto_mix_enabled = False
    frame._auto_remove_played = False
    frame._focus_playing_track = False
    frame._active_break_item = {}
    frame._auto_mix_tracker = SimpleNamespace(set_last_started=lambda *_a, **_k: None)
    frame._announce_event = lambda *_a, **_k: None
    frame._clear_mix_plan = lambda *_a, **_k: None

    started: list[dict] = []
    frame._start_next_from_playlist = lambda *_a, **kwargs: started.append(kwargs) or True

    path_a = tmp_path / "a.wav"
    path_b = tmp_path / "b.wav"
    path_a.write_text("dummy")
    path_b.write_text("dummy")
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    finished = PlaylistItem(id="a", path=path_a, title="A", duration_seconds=1.0, status=PlaylistItemStatus.PLAYING)
    queued = PlaylistItem(id="b", path=path_b, title="B", duration_seconds=1.0)
    queued.is_selected = True
    playlist.add_items([finished, queued])

    class _Panel:
        def __init__(self, model):
            self.model = model

        def mark_item_status(self, *_a, **_k):
            return None

        def refresh(self, *_a, **_k):
            return None

        def get_selected_indices(self):
            return []

        def get_focused_index(self):
            return -1

        def select_index(self, *_a, **_k):
            return None

    panel = _Panel(playlist)
    _register_playlist(frame, playlist, panel)

    player = SimpleNamespace(
        set_finished_callback=lambda *_a, **_k: None,
        set_progress_callback=lambda *_a, **_k: None,
        stop=lambda *_a, **_k: None,
    )
    key = (playlist.id, finished.id)
    frame._playback = SimpleNamespace(
        auto_mix_state={},
        contexts={key: SimpleNamespace(player=player)},
        get_context=lambda _pid: None,
    )

    frame._handle_playback_finished(playlist.id, finished.id)

    assert started
    assert started[-1].get("ignore_ui_selection") is True


def test_play_item_direct_prefers_queued_selection_over_requested_item(tmp_path, monkeypatch):
    frame = MainFrame.__new__(MainFrame)
    frame._auto_mix_enabled = False
    frame._announce_event = lambda *_a, **_k: None
    frame._auto_mix_play_next = lambda *_a, **_k: False

    started: list[dict] = []
    frame._start_next_from_playlist = lambda *_a, **kwargs: started.append(kwargs) or True

    path_a = tmp_path / "a.wav"
    path_b = tmp_path / "b.wav"
    path_a.write_text("dummy")
    path_b.write_text("dummy")
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    queued = PlaylistItem(id="a", path=path_a, title="A", duration_seconds=1.0)
    queued.is_selected = True
    other = PlaylistItem(id="b", path=path_b, title="B", duration_seconds=1.0)
    playlist.add_items([queued, other])

    from sara.ui import main_frame as main_frame_module

    class _FakePlaylistPanel:
        def __init__(self, model):
            self.model = model

    monkeypatch.setattr(main_frame_module, "PlaylistPanel", _FakePlaylistPanel)

    panel = _FakePlaylistPanel(playlist)
    _register_playlist(frame, playlist, panel)
    if not hasattr(frame, "_playlists"):
        frame._playlists = {}
    frame._playlists[playlist.id] = panel

    assert frame._play_item_direct(playlist.id, other.id) is True
    assert started
    assert started[-1].get("ignore_ui_selection") is True


def test_pfl_mix_preview_uses_mix_timing(tmp_path):
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    track_a = PlaylistItem(
        id="a",
        path=tmp_path / "a.wav",
        title="A",
        duration_seconds=10.0,
        cue_in_seconds=1.0,
        segue_seconds=3.0,
    )
    track_b = PlaylistItem(
        id="b",
        path=tmp_path / "b.wav",
        title="B",
        duration_seconds=8.0,
        cue_in_seconds=0.5,
    )
    playlist.add_items([track_a, track_b])

    calls: dict[str, tuple] = {}

    class _SpyPlayback:
        def start_mix_preview(
            self,
            current_item,
            next_item,
            *,
            mix_at_seconds,
            pre_seconds,
            fade_seconds,
            current_effective_duration,
            next_cue_override,
        ):
            calls["args"] = (
                current_item,
                next_item,
                mix_at_seconds,
                pre_seconds,
                fade_seconds,
                current_effective_duration,
                next_cue_override,
            )
            return True

    frame = MainFrame.__new__(MainFrame)
    frame._playback = _SpyPlayback()
    frame._settings = SimpleNamespace(get_pfl_device=lambda: "pfl-dev")
    frame._fade_duration = 2.0
    frame._mix_trigger_points = {}
    frame._playlists = {"pl-1": SimpleNamespace(model=playlist)}
    frame._announce_event = lambda *args, **kwargs: None
    frame._index_of_item = lambda _pl, _id: 0

    ok = frame._preview_mix_with_next(playlist, track_a, overrides=None)
    assert ok is True
    assert "args" in calls
    _cur, _nxt, mix_at, pre_secs, fade_secs, eff, next_cue = calls["args"]
    assert abs(mix_at - 4.0) < 1e-6
    assert abs(pre_secs - 4.0) < 1e-6
    assert abs(fade_secs - 2.0) < 1e-6
    assert abs(eff - 9.0) < 1e-6
    assert abs(next_cue - 0.5) < 1e-6


def test_pfl_mix_preview_uses_measured_effective_duration(tmp_path):
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    track_a = PlaylistItem(
        id="a",
        path=tmp_path / "a.wav",
        title="A",
        duration_seconds=10.0,
        cue_in_seconds=1.0,
    )
    track_b = PlaylistItem(
        id="b",
        path=tmp_path / "b.wav",
        title="B",
        duration_seconds=8.0,
        cue_in_seconds=0.5,
    )
    playlist.add_items([track_a, track_b])

    captured: dict[str, tuple] = {}

    class _SpyPlayback:
        def start_mix_preview(
            self,
            current_item,
            next_item,
            *,
            mix_at_seconds,
            pre_seconds,
            fade_seconds,
            current_effective_duration,
            next_cue_override,
        ):
            captured["args"] = (
                current_item,
                next_item,
                mix_at_seconds,
                pre_seconds,
                fade_seconds,
                current_effective_duration,
                next_cue_override,
            )
            return True

    frame = MainFrame.__new__(MainFrame)
    frame._playback = _SpyPlayback()
    frame._settings = SimpleNamespace(get_pfl_device=lambda: "pfl-dev")
    frame._fade_duration = 2.0
    frame._mix_trigger_points = {}
    frame._playlists = {"pl-1": SimpleNamespace(model=playlist)}
    frame._announce_event = lambda *args, **kwargs: None
    frame._index_of_item = lambda _pl, _id: 0
    frame._measure_effective_duration = lambda _playlist, _item: 5.0

    ok = frame._preview_mix_with_next(playlist, track_a, overrides=None)
    assert ok is True
    _cur, _nxt, mix_at, pre_secs, _fade_secs, eff, _next_cue = captured["args"]
    assert abs(mix_at - 4.0) < 1e-6
    assert abs(eff - 5.0) < 1e-6
    assert abs(pre_secs - 4.0) < 1e-6


def test_pfl_mix_preview_fails_without_device(tmp_path):
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    track_a = PlaylistItem(
        id="a",
        path=tmp_path / "a.wav",
        title="A",
        duration_seconds=10.0,
    )
    track_b = PlaylistItem(
        id="b",
        path=tmp_path / "b.wav",
        title="B",
        duration_seconds=8.0,
    )
    playlist.add_items([track_a, track_b])

    class _NoDevicePlayback:
        def start_mix_preview(self, *args, **kwargs):
            return False

    frame = MainFrame.__new__(MainFrame)
    frame._playback = _NoDevicePlayback()
    frame._settings = SimpleNamespace(get_pfl_device=lambda: None)
    frame._fade_duration = 2.0
    frame._mix_trigger_points = {}
    frame._playlists = {"pl-1": SimpleNamespace(model=playlist)}
    frame._announce_event = lambda *args, **kwargs: None
    frame._index_of_item = lambda _pl, _id: 0

    ok = frame._preview_mix_with_next(playlist, track_a, overrides=None)
    assert ok is False


def test_loop_hold_blocks_auto_mix_play_next():
    frame = MainFrame.__new__(MainFrame)
    frame._fade_duration = 2.0
    frame._auto_mix_enabled = True
    frame._auto_mix_busy = {}
    frame._last_started_item_id = {}
    stopped: list[str] = []
    frame._playback = SimpleNamespace(
        auto_mix_state={("pl-1", "i1"): "loop_hold"},
        stop_playlist=lambda pl_id, fade_duration=0.0: stopped.append(pl_id) or [((pl_id, "i1"), None)],
        contexts={("pl-1", "i1"): SimpleNamespace(player=None)},
        get_context=lambda pl_id: next((((k, v) for k, v in frame._playback.contexts.items() if k[0] == pl_id)), None),
    )
    frame._mix_plans = {}
    frame._mix_trigger_points = {}
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    playlist.items = [PlaylistItem(id="i1", path=Path("a"), title="A", duration_seconds=1.0)]
    panel = SimpleNamespace(
        model=playlist,
        mark_item_status=lambda *_a, **_k: None,
        update_progress=lambda *_a, **_k: None,
        refresh=lambda *_a, **_k: None,
    )
    frame._playlists = {"pl-1": panel}
    frame._auto_mix_tracker = SimpleNamespace(
        next_index=lambda *args, **kwargs: 0,
        _last_item_id={},
        stage_next=lambda *a, **k: None,
        set_last_started=lambda *_a, **_k: None,
    )
    frame._start_playback = lambda *args, **kwargs: True
    result = frame._auto_mix_play_next(panel)
    assert result is True
    assert stopped and stopped[0] == "pl-1"


def test_loop_hold_play_next_advances_cursor(tmp_path):
    playlist = PlaylistModel(id="pl-hold", name="Loop Hold", kind=PlaylistKind.MUSIC)
    intro = PlaylistItem(id="intro", path=tmp_path / "intro.wav", title="Intro", duration_seconds=5.0)
    intro.status = PlaylistItemStatus.PLAYED
    bed = PlaylistItem(
        id="bed",
        path=tmp_path / "bed.wav",
        title="Bed",
        duration_seconds=30.0,
        loop_enabled=True,
        loop_start_seconds=5.0,
        loop_end_seconds=20.0,
    )
    bed.status = PlaylistItemStatus.PLAYING
    jingle = PlaylistItem(id="jingle", path=tmp_path / "jingle.wav", title="Jingle", duration_seconds=8.0)
    playlist.add_items([intro, bed, jingle])
    panel = SimpleNamespace(
        model=playlist,
        mark_item_status=lambda *_a, **_k: None,
        update_progress=lambda *_a, **_k: None,
        refresh=lambda *_a, **_k: None,
    )

    frame = MainFrame.__new__(MainFrame)
    frame._fade_duration = 1.0
    frame._auto_mix_enabled = True
    frame._auto_mix_busy = {}
    frame._last_started_item_id = {}
    tracker = AutoMixTracker()
    tracker.set_last_started(playlist.id, intro.id)
    frame._auto_mix_tracker = tracker
    frame._playlists = {playlist.id: panel}
    frame._mix_plans = {}
    frame._mix_trigger_points = {}

    def _stop_playlist(pl_id, fade_duration=0.0):
        assert pl_id == playlist.id
        return [((pl_id, bed.id), None)]

    frame._playback = SimpleNamespace(
        auto_mix_state={(playlist.id, bed.id): "loop_hold"},
        stop_playlist=_stop_playlist,
        contexts={(playlist.id, bed.id): SimpleNamespace(player=None)},
        get_context=lambda _pl_id: None,
    )

    started_indices: list[int] = []

    def _auto_mix_start_index(panel_arg, idx, **kwargs):
        assert panel_arg is panel
        started_indices.append(idx)
        return True

    frame._auto_mix_start_index = _auto_mix_start_index

    result = frame._auto_mix_play_next(panel)

    assert result is True
    assert started_indices == [2]
    assert frame._auto_mix_tracker._last_item_id[playlist.id] == bed.id
    assert frame._last_started_item_id[playlist.id] == bed.id


def test_stop_playlist_clears_mix_plan_and_state(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._mix_plans = {("pl-1", "item-1"): None}
    frame._mix_trigger_points = {("pl-1", "item-1"): 5.0}
    frame._playback = SimpleNamespace(
        stop_playlist=lambda *_args, **_kwargs: [(("pl-1", "item-1"), None)],
        clear_auto_mix=lambda: None,
    )
    frame._playlists = {"pl-1": SimpleNamespace(model=PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC))}
    frame._active_break_item = {}
    frame._announce_event = lambda *args, **kwargs: None
    frame._stop_playlist_playback("pl-1", mark_played=False, fade_duration=0.0)
    assert frame._mix_plans == {}
    assert frame._mix_trigger_points == {}


def test_clear_playlist_entries_removes_mix_plans(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._mix_plans = {("pl-1", "item-1"): None, ("pl-1", "item-2"): None}
    frame._mix_trigger_points = {("pl-1", "item-1"): 5.0, ("pl-1", "item-2"): 6.0}
    playback = SimpleNamespace(
        contexts={(("pl-1", "item-1")): None, (("pl-1", "item-2")): None},
        clear_auto_mix=lambda: None,
        clear_playlist_entries=lambda playlist_id: playback.contexts.clear(),
    )
    frame._playback = playback
    model = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    model.items = [
        PlaylistItem(id="item-1", path=tmp_path / "a", title="A", duration_seconds=1.0),
        PlaylistItem(id="item-2", path=tmp_path / "b", title="B", duration_seconds=1.0),
    ]
    frame._playlists = {"pl-1": SimpleNamespace(model=model)}
    frame._cleanup_unused_mixers = lambda: None
    frame._playback.clear_playlist_entries("pl-1")
    frame._clear_mix_plan("pl-1", "item-1")
    frame._clear_mix_plan("pl-1", "item-2")
    assert frame._mix_plans == {}
    assert frame._mix_trigger_points == {}


def test_mix_point_changes_propagate_to_duplicates(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    path = tmp_path / "dup.wav"
    path.write_text("dup")
    playlist = PlaylistModel(id="pl-dup", name="Dup", kind=PlaylistKind.MUSIC)
    first = PlaylistItem(id="a", path=path, title="A", duration_seconds=10.0, segue_seconds=5.0)
    duplicate = PlaylistItem(id="b", path=path, title="B", duration_seconds=10.0, segue_seconds=5.0)
    playlist.add_items([first, duplicate])
    refresh_calls: list[object] = []
    panel = SimpleNamespace(model=playlist, refresh=lambda *args, **kwargs: refresh_calls.append(object()))
    frame._playlists = {playlist.id: panel}
    frame._playback = SimpleNamespace(auto_mix_state={}, contexts={})
    frame._mix_plans = {
        (playlist.id, duplicate.id): MixPlan(
            mix_at=5.0,
            fade_seconds=1.0,
            base_cue=0.0,
            effective_duration=10.0,
            native_trigger=False,
        )
    }
    frame._mix_trigger_points = {(playlist.id, duplicate.id): 5.0}

    mix_values = {"cue_in": 1.0, "intro": 2.0, "outro": 8.0, "segue": 6.0, "overlap": 1.5}
    frame._propagate_mix_points_for_path(
        path=path,
        mix_values=mix_values,
        source_playlist_id=playlist.id,
        source_item_id=first.id,
    )

    assert duplicate.cue_in_seconds == 1.0
    assert duplicate.segue_seconds == 6.0
    assert (playlist.id, duplicate.id) not in frame._mix_plans
    assert refresh_calls


def test_auto_mix_enable_starts_selected_track(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._auto_mix_enabled = False
    playlist = PlaylistModel(id="pl-auto-select", name="Auto", kind=PlaylistKind.MUSIC)
    items = [
        PlaylistItem(id=f"item-{idx}", path=tmp_path / f"{idx}.wav", title=f"Track {idx}", duration_seconds=10.0)
        for idx in range(4)
    ]
    playlist.add_items(items)
    selected_idx = 2

    panel = SimpleNamespace(
        model=playlist,
        get_selected_indices=lambda: [selected_idx],
        get_focused_index=lambda: selected_idx,
    )
    frame._playback = SimpleNamespace(contexts={}, auto_mix_state={}, clear_auto_mix=lambda: None)
    frame._auto_mix_tracker = AutoMixTracker()
    frame._get_current_music_panel = lambda: panel
    frame._get_playback_context = lambda _pid=None: None
    frame._announce_event = lambda *_args, **_kwargs: None
    started: list[tuple[int, bool]] = []
    frame._auto_mix_start_index = lambda _p, idx, restart_playing: started.append((idx, restart_playing)) or True

    frame._set_auto_mix_enabled(True)

    assert frame._auto_mix_enabled is True
    assert started == [(selected_idx, False)]


def test_manual_fade_disables_auto_mix(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._auto_mix_enabled = True
    frame._fade_duration = 2.0
    frame._state = AppState()
    playlist = PlaylistModel(id="pl-manual", name="Manual", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-manual",
        path=tmp_path / "manual.wav",
        title="Manual",
        duration_seconds=8.0,
    )
    item.current_position = 1.0
    playlist.add_items([item])
    panel = SimpleNamespace(
        model=playlist,
        get_selected_indices=lambda: [],
        get_focused_index=lambda: 0,
        mark_item_status=lambda *_a, **_k: None,
        refresh=lambda *_a, **_k: None,
    )
    context_key = (playlist.id, item.id)
    ctx = SimpleNamespace(player=_DummyPlayer("dev-1"))
    frame._playlists = {playlist.id: panel}
    frame._get_current_music_panel = lambda: panel
    frame._mix_plans = {
        (playlist.id, item.id): MixPlan(
            mix_at=6.0,
            fade_seconds=4.0,
            base_cue=0.0,
            effective_duration=8.0,
            native_trigger=False,
        )
    }
    frame._playback = SimpleNamespace(
        auto_mix_state={},
        contexts={context_key: ctx},
        clear_auto_mix=lambda: None,
    )
    frame._get_playback_context = lambda pl_id=None: (context_key, ctx) if pl_id == playlist.id else None
    captured: dict[str, float] = {}

    def _capture_stop(_pl_id, *, mark_played: bool, fade_duration: float):
        captured["fade_duration"] = fade_duration

    frame._stop_playlist_playback = _capture_stop
    frame._announce_event = lambda *_a, **_k: None
    frame._action_by_id = {1: "fade"}

    event = SimpleNamespace(GetId=lambda: 1)
    frame._on_playlist_hotkey(event)

    assert frame._auto_mix_enabled is False
    assert captured["fade_duration"] == pytest.approx(4.0)

