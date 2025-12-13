from __future__ import annotations

from pathlib import Path
import shutil
from threading import Event
from typing import Callable, Optional

from types import SimpleNamespace

import pytest

from sara.core.app_state import AppState
from sara.core.config import SettingsManager
from sara.core.playlist import PlaylistItem, PlaylistModel, PlaylistKind, PlaylistItemStatus
from sara.audio.engine import BackendType
from sara.ui.main_frame import MainFrame, MIX_NATIVE_LATE_GUARD, MixPlan
from sara.ui.auto_mix_tracker import AutoMixTracker
from sara.ui.playback_controller import PlaybackController
from sara.core.media_metadata import extract_metadata


class _DummyDevice:
    def __init__(self, id: str):
        self.id = id
        self.name = id
        self.backend = BackendType.WASAPI


class _DummyPlayer:
    def __init__(self, device_id: str, supports: bool = True):
        self.device_id = device_id
        self._supports = supports
        self.play_calls: list[dict] = []
        self.mix_calls: list[tuple[Optional[float], Optional[Callable]]] = []
        self.finished_callback: Optional[Callable[[str], None]] = None
        self.progress_callback: Optional[Callable[[str, float], None]] = None

    # ---- interface expected by PlaybackController ----
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


class _DummyAudioEngine:
    def __init__(self, *, supports_mix_trigger: bool):
        self._supports = supports_mix_trigger
        self._devices = [_DummyDevice("dev-1")]
        self.players: list[_DummyPlayer] = []

    def get_devices(self):
        return self._devices

    def refresh_devices(self):
        return None

    def create_player(self, device_id: str):
        player = _DummyPlayer(device_id, supports=self._supports)
        self.players.append(player)
        return player

    def stop_all(self):
        return None


def _playlist_with_item(tmp_path: Path) -> tuple[PlaylistModel, PlaylistItem]:
    playlist = PlaylistModel(id="pl-1", name="Test", kind=PlaylistKind.MUSIC)
    playlist.set_output_slots(["dev-1"])
    track_path = tmp_path / "track.mp3"
    track_path.write_text("dummy")
    item = PlaylistItem(
        id="item-1",
        path=track_path,
        title="Track",
        duration_seconds=10.0,
        segue_seconds=4.0,
    )
    playlist.add_items([item])
    return playlist, item


def test_start_item_passes_mix_trigger_only_when_supported(tmp_path):
    playlist, item = _playlist_with_item(tmp_path)
    settings = SettingsManager(config_path=tmp_path / "settings.yaml")

    audio = _DummyAudioEngine(supports_mix_trigger=True)
    controller = PlaybackController(audio, settings, lambda *_args: None)
    controller.start_item(
        playlist,
        item,
        start_seconds=0.0,
        on_finished=lambda _item_id: None,
        on_progress=lambda _item_id, _seconds: None,
        mix_trigger_seconds=4.0,
        on_mix_trigger=lambda: None,
    )
    play_kwargs = audio.players[0].play_calls[-1]
    assert play_kwargs["mix_trigger_seconds"] == 4.0
    assert callable(play_kwargs["on_mix_trigger"])

    playlist2, item2 = _playlist_with_item(tmp_path)
    audio_no_support = _DummyAudioEngine(supports_mix_trigger=False)
    controller_no_support = PlaybackController(audio_no_support, settings, lambda *_args: None)
    controller_no_support.start_item(
        playlist2,
        item2,
        start_seconds=0.0,
        on_finished=lambda _item_id: None,
        on_progress=lambda _item_id, _seconds: None,
        mix_trigger_seconds=4.0,
        on_mix_trigger=lambda: None,
    )
    play_kwargs = audio_no_support.players[0].play_calls[-1]
    assert play_kwargs["mix_trigger_seconds"] is None
    assert play_kwargs["on_mix_trigger"] is None


def test_update_mix_trigger_respects_player_support(tmp_path):
    playlist, item = _playlist_with_item(tmp_path)
    settings = SettingsManager(config_path=tmp_path / "settings.yaml")

    # unsupported player -> no setter call, returns False
    audio_no_support = _DummyAudioEngine(supports_mix_trigger=False)
    controller = PlaybackController(audio_no_support, settings, lambda *_args: None)
    controller.start_item(
        playlist,
        item,
        start_seconds=0.0,
        on_finished=lambda _item_id: None,
        on_progress=lambda _item_id, _seconds: None,
    )
    assert controller.update_mix_trigger(playlist.id, item.id, mix_trigger_seconds=3.0, on_mix_trigger=lambda: None) is False
    assert audio_no_support.players[0].mix_calls == []

    # supported player -> setter called, returns True
    playlist2, item2 = _playlist_with_item(tmp_path)
    audio_support = _DummyAudioEngine(supports_mix_trigger=True)
    controller2 = PlaybackController(audio_support, settings, lambda *_args: None)
    controller2.start_item(
        playlist2,
        item2,
        start_seconds=0.0,
        on_finished=lambda _item_id: None,
        on_progress=lambda _item_id, _seconds: None,
    )
    on_trigger = lambda: None
    assert controller2.update_mix_trigger(playlist2.id, item2.id, mix_trigger_seconds=5.0, on_mix_trigger=on_trigger) is True
    assert audio_support.players[0].mix_calls == [(5.0, on_trigger)]


def test_mix_plan_register_and_clear():
    frame = MainFrame.__new__(MainFrame)
    frame._mix_plans = {}
    frame._mix_trigger_points = {}

    frame._register_mix_plan(
        "pl-1",
        "item-1",
        mix_at=5.0,
        fade_seconds=2.5,
        base_cue=1.0,
        effective_duration=9.0,
        native_trigger=True,
    )
    key = ("pl-1", "item-1")
    assert key in frame._mix_plans
    assert frame._mix_trigger_points[key] == 5.0
    assert frame._mix_plans[key].fade_seconds == 2.5
    frame._mark_mix_triggered("pl-1", "item-1")
    assert frame._mix_plans[key].triggered is True
    frame._clear_mix_plan("pl-1", "item-1")
    assert frame._mix_plans == {}
    assert frame._mix_trigger_points == {}


def test_undo_like_remove_clears_mix_state(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._mix_plans = {("pl-1", "item-1"): None}
    frame._mix_trigger_points = {("pl-1", "item-1"): 5.0}
    frame._playback = SimpleNamespace(
        contexts={( "pl-1","item-1"): SimpleNamespace(player=None)},
        clear_auto_mix=lambda: None,
        stop_playlist=lambda _pl_id, fade_duration=0.0: [(( "pl-1","item-1"), None)],
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
    # symulacja usunięcia grającego utworu (undo/redo podobna ścieżka)
    frame._remove_item_from_playlist = lambda _panel, _model, idx, refocus=True: _model.items.pop(idx)
    frame._stop_playlist_playback("pl-1", mark_played=False, fade_duration=0.0)
    assert ("pl-1", "item-1") not in frame._mix_trigger_points
    assert ("pl-1", "item-1") not in frame._mix_plans


def test_resolve_mix_timing_matches_editor_markers():
    frame = MainFrame.__new__(MainFrame)
    frame._fade_duration = 2.0
    item = PlaylistItem(
        id="i1",
        path=Path("x"),
        title="T",
        duration_seconds=11.0,
        cue_in_seconds=1.0,
        segue_seconds=3.0,
        overlap_seconds=None,
    )
    mix_at, fade, base_cue, effective = frame._resolve_mix_timing(item)
    # segue ma pierwszeństwo nad overlap, baza to cue
    assert base_cue == 1.0
    assert effective == 10.0
    assert mix_at == 4.0
    assert fade == 2.0

    item2 = PlaylistItem(
        id="i2",
        path=Path("x"),
        title="T",
        duration_seconds=11.0,
        cue_in_seconds=1.0,
        segue_seconds=None,
        overlap_seconds=2.5,
    )
    mix_at2, fade2, base_cue2, effective2 = frame._resolve_mix_timing(item2)
    # overlap bez segue: mix przy końcu, fade=overlap
    assert base_cue2 == 1.0
    assert effective2 == 10.0
    assert mix_at2 == 8.5  # 1 + (10 - 2.5)
    assert fade2 == 2.5

    item3 = PlaylistItem(
        id="i3",
        path=Path("x"),
        title="T",
        duration_seconds=11.0,
        cue_in_seconds=1.0,
        segue_seconds=None,
        overlap_seconds=None,
    )
    mix_at3, fade3, base_cue3, effective3 = frame._resolve_mix_timing(item3)
    # brak markerów: użyj globalnego fade
    assert base_cue3 == 1.0
    assert effective3 == 10.0
    assert mix_at3 == 9.0  # 1 + (10 - fade(2))
    assert fade3 == 2.0


def test_resolve_mix_timing_honours_segue_fade_override():
    frame = MainFrame.__new__(MainFrame)
    frame._fade_duration = 2.0
    item = PlaylistItem(
        id="i4",
        path=Path("x"),
        title="Fade override",
        duration_seconds=12.0,
        cue_in_seconds=1.0,
        segue_seconds=4.0,
        segue_fade_seconds=0.5,
        overlap_seconds=None,
    )
    mix_at, fade, base_cue, effective = frame._resolve_mix_timing(item)
    assert base_cue == 1.0
    assert effective == 11.0
    assert mix_at == pytest.approx(5.0, rel=1e-6)
    assert fade == pytest.approx(0.5, rel=1e-6)


def test_progress_based_mix_triggers_when_native_missing(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._fade_duration = 3.0
    frame._mix_plans = {}
    frame._mix_trigger_points = {}
    frame._auto_mix_enabled = True
    frame._active_break_item = {}
    frame._playback = SimpleNamespace(auto_mix_state={}, contexts={})
    frame._supports_mix_trigger = lambda player: getattr(player, "supports_mix_trigger", lambda: False)()

    class _ProgressPlayer(_DummyPlayer):
        def __init__(self, device_id: str):
            super().__init__(device_id, supports=False)
            self.fade_calls: list[float] = []

        def fade_out(self, duration: float):
            self.fade_calls.append(duration)

    item = PlaylistItem(
        id="mix-1",
        path=tmp_path / "a.wav",
        title="A",
        duration_seconds=12.0,
        cue_in_seconds=0.0,
        overlap_seconds=3.0,
    )
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    playlist.add_items([item])
    panel = SimpleNamespace(model=playlist)
    _register_playlist(frame, playlist, panel)
    player = _ProgressPlayer("dev-1")
    ctx = SimpleNamespace(player=player)

    # simulate progress near mix point (effective 12, overlap 3 -> mix_at 9)
    frame._start_next_from_playlist = lambda *args, **kwargs: True
    frame._auto_mix_state_process(panel, item, ctx, seconds=9.1, queued_selection=False)
    key = (playlist.id, item.id)
    assert frame._playback.auto_mix_state[key] is True
    assert frame._mix_plans[key].triggered is True
    # fade should use min(fade, remaining)
    assert player.fade_calls and abs(player.fade_calls[0] - 2.9) < 1e-6  # remaining 2.9s


def test_break_clears_mix_plan(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._mix_plans = {("pl-1", "item-1"): None}
    frame._mix_trigger_points = {("pl-1", "item-1"): 5.0}
    frame._playback = SimpleNamespace(
        update_mix_trigger=lambda *_args, **_kwargs: True,
        contexts={},
        auto_mix_state={},
    )
    frame._supports_mix_trigger = lambda _p: False
    frame._register_mix_plan = lambda *args, **kwargs: None
    panel = SimpleNamespace(model=PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC))
    item = PlaylistItem(
        id="item-1",
        path=tmp_path / "a.wav",
        title="A",
        duration_seconds=10.0,
    )
    item.break_after = True
    frame._apply_mix_trigger_to_playback(playlist_id="pl-1", item=item, panel=panel)
    assert frame._mix_plans == {}
    assert frame._mix_trigger_points == {}


def test_loop_hold_clears_mix_plan_and_sets_flag(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._auto_mix_enabled = False
    frame._fade_duration = 2.0
    frame._mix_plans = {("pl-1", "item-1"): None}
    frame._mix_trigger_points = {("pl-1", "item-1"): 5.0}
    auto_state = {}
    frame._playback = SimpleNamespace(
        auto_mix_state=auto_state,
        update_mix_trigger=lambda *_args, **_kwargs: True,
    )
    frame._clear_mix_plan = lambda pl_id, item_id: (frame._mix_plans.pop((pl_id, item_id), None), frame._mix_trigger_points.pop((pl_id, item_id), None))
    frame._supports_mix_trigger = lambda _p: False
    frame._register_mix_plan = lambda *args, **kwargs: None

    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-1",
        path=tmp_path / "a.wav",
        title="A",
        duration_seconds=10.0,
        loop_start_seconds=1.0,
        loop_end_seconds=3.0,
        loop_enabled=True,
    )
    context = SimpleNamespace(player=_DummyPlayer("dev-1"))
    frame._sync_loop_mix_trigger(panel=None, playlist=playlist, item=item, context=context)
    assert ("pl-1", "item-1") not in frame._mix_trigger_points
    assert auto_state[("pl-1", "item-1")] == "loop_hold"


def test_loop_hold_in_automix_does_not_auto_advance(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._auto_mix_enabled = True
    frame._fade_duration = 1.5
    frame._mix_plans = {("pl-1", "item-1"): None}
    frame._mix_trigger_points = {("pl-1", "item-1"): 4.0}
    auto_state: dict = {}
    frame._playback = SimpleNamespace(
        auto_mix_state=auto_state,
        update_mix_trigger=lambda *_args, **_kwargs: True,
    )
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-1",
        path=tmp_path / "loop.wav",
        title="Loop",
        duration_seconds=10.0,
        loop_start_seconds=2.0,
        loop_end_seconds=4.0,
        loop_enabled=True,
    )
    playlist.add_items([item])
    panel = SimpleNamespace(model=playlist)
    _register_playlist(frame, playlist, panel)
    context = SimpleNamespace(player=_DummyPlayer("dev-1"))
    auto_next_calls: list[object] = []
    frame._auto_mix_tracker = SimpleNamespace(set_last_started=lambda *_a, **_k: None)
    frame._auto_mix_play_next = lambda *_a, **_k: auto_next_calls.append(object())

    frame._sync_loop_mix_trigger(panel=panel, playlist=playlist, item=item, context=context)

    assert auto_state[("pl-1", "item-1")] == "loop_hold"
    assert ("pl-1", "item-1") not in frame._mix_trigger_points
    assert auto_next_calls == []


def test_auto_mix_state_process_skips_loop_hold(tmp_path):
    frame = _make_frame_for_automix(fade=2.0)
    playlist = PlaylistModel(id="pl-loop", name="Looping", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="looped",
        path=tmp_path / "looped.wav",
        title="Looped",
        duration_seconds=12.0,
        loop_enabled=True,
        loop_start_seconds=2.0,
        loop_end_seconds=6.0,
    )
    playlist.add_items([item])
    panel = SimpleNamespace(model=playlist)
    _register_playlist(frame, playlist, panel)
    key = (playlist.id, item.id)
    player = _AutoMixPlayer("dev-1")
    ctx = SimpleNamespace(player=player)
    frame._playback.auto_mix_state[key] = "loop_hold"
    frame._playback.contexts[key] = ctx
    started: list[dict] = []
    frame._start_next_from_playlist = lambda *_a, **_k: started.append({}) or True

    frame._auto_mix_state_process(panel, item, ctx, seconds=5.0, queued_selection=False)

    assert started == []
    assert player.fade_calls == []
    assert frame._playback.auto_mix_state[key] == "loop_hold"


def test_early_native_trigger_reschedules_mix_point(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._fade_duration = 2.0
    key = ("pl-1", "item-1")
    plan = SimpleNamespace(mix_at=8.0, fade_seconds=2.0, base_cue=0.0, effective_duration=12.0, native_trigger=True, triggered=False)
    frame._mix_plans = {key: plan}
    frame._mix_trigger_points = {key: 8.0}
    update_calls: list[tuple] = []

    def _update_mix_trigger(pl_id, item_id, mix_trigger_seconds=None, on_mix_trigger=None):
        update_calls.append((pl_id, item_id, mix_trigger_seconds, on_mix_trigger))
        return True

    class _NativePlayer(_DummyPlayer):
        def __init__(self):
            super().__init__("dev-1", supports=True)

        def get_length_seconds(self):
            return 12.0

    player = _NativePlayer()
    frame._supports_mix_trigger = lambda _p: True
    frame._playlist_has_selection = lambda _pid: False
    frame._auto_mix_enabled = True
    frame._active_break_item = {}
    frame._playback = SimpleNamespace(
        auto_mix_state={},
        contexts={key: SimpleNamespace(player=player)},
        update_mix_trigger=_update_mix_trigger,
    )
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-1",
        path=tmp_path / "a.wav",
        title="A",
        duration_seconds=12.0,
        cue_in_seconds=0.0,
        segue_seconds=8.0,
        current_position=1.0,
    )
    panel = SimpleNamespace(model=playlist)

    # Backend wystrzelił za wcześnie: powinno się przerejestrować trigger i nie startować miksu od razu.
    frame._auto_mix_now(playlist, item, panel)
    assert update_calls and update_calls[0][2] is None
    assert frame._mix_plans[key].native_trigger is False
    assert frame._mix_plans[key].mix_at == pytest.approx(8.0, rel=1e-3)
    assert frame._mix_plans[key].triggered is False
    assert frame._playback.auto_mix_state == {}


def test_native_fallback_triggers_progress_mix(tmp_path):
    frame = _make_frame_for_automix(fade=2.0)
    frame._supports_mix_trigger = lambda _p: True
    playlist = PlaylistModel(id="pl-fallback", name="Fallback", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-1",
        path=tmp_path / "a.wav",
        title="A",
        duration_seconds=20.0,
        segue_seconds=15.0,
        cue_in_seconds=0.0,
        current_position=1.0,
    )
    playlist.add_items([item])
    panel = SimpleNamespace(model=playlist)
    player = _AutoMixPlayer("dev-1", supports_mix_trigger=True)
    key = (playlist.id, item.id)
    update_calls: list[tuple] = []
    def _record_update(pl_id, item_id, *, mix_trigger_seconds=None, on_mix_trigger=None):
        update_calls.append((pl_id, item_id, mix_trigger_seconds, on_mix_trigger))
        return True

    frame._playback = SimpleNamespace(
        auto_mix_state={},
        contexts={key: SimpleNamespace(player=player)},
        update_mix_trigger=_record_update,
    )
    frame._mix_plans[key] = MixPlan(
        mix_at=15.0,
        fade_seconds=frame._fade_duration,
        base_cue=0.0,
        effective_duration=item.effective_duration_seconds,
        native_trigger=True,
    )
    frame._mix_trigger_points[key] = 15.0
    started: list[dict] = []
    frame._start_next_from_playlist = lambda *_a, **_k: started.append({}) or True

    # Backend strzelił za wcześnie – przejdź na fallback progresowy
    frame._auto_mix_now(playlist, item, panel)
    assert update_calls and update_calls[-1][2] is None
    assert frame._mix_plans[key].native_trigger is False

    ctx = frame._playback.contexts[key]
    frame._auto_mix_state_process(panel, item, ctx, seconds=15.2, queued_selection=False)
    assert started, "Fallback progresowy powinien wystartować miks"


def test_manual_selection_triggers_mix_when_auto_mix_disabled(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._fade_duration = 2.0
    frame._mix_plans = {}
    frame._mix_trigger_points = {}
    frame._auto_mix_enabled = False
    frame._active_break_item = {}
    auto_state = {}
    frame._playback = SimpleNamespace(auto_mix_state=auto_state, contexts={})
    frame._supports_mix_trigger = lambda _p: False

    class _SelectPlayer(_DummyPlayer):
        def __init__(self):
            super().__init__("dev-1", supports=False)
            self.fade_calls: list[float] = []

        def fade_out(self, duration: float):
            self.fade_calls.append(duration)

    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-1",
        path=tmp_path / "a.wav",
        title="A",
        duration_seconds=10.0,
        cue_in_seconds=0.0,
        overlap_seconds=2.0,
    )
    playlist.add_items([item])
    panel = SimpleNamespace(model=playlist)
    player = _SelectPlayer()
    ctx = SimpleNamespace(player=player)
    frame._start_next_from_playlist = lambda *args, **kwargs: True
    frame._playlist_has_selection = lambda _pid: True
    frame._auto_mix_play_next = lambda _panel: True

    frame._auto_mix_state_process(panel, item, ctx, seconds=9.0, queued_selection=True)
    key = (playlist.id, item.id)
    assert auto_state[key] is True
    assert frame._mix_plans[key].triggered is True
    assert player.fade_calls and abs(player.fade_calls[0] - 1.0) < 1e-6  # remaining 1s


def test_late_native_trigger_falls_back_to_progress(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._fade_duration = 2.0
    key = ("pl-1", "item-1")
    frame._mix_plans = {}
    frame._mix_trigger_points = {key: 5.0}
    frame._auto_mix_enabled = True
    frame._active_break_item = {}
    auto_state = {}
    updates: list = []

    class _LatePlayer(_DummyPlayer):
        def __init__(self):
            super().__init__("dev-1", supports=True)
            self.fade_calls: list[float] = []

        def fade_out(self, duration: float):
            self.fade_calls.append(duration)

        def get_length_seconds(self):
            return 12.0

    player = _LatePlayer()
    frame._supports_mix_trigger = lambda _p: True
    frame._playback = SimpleNamespace(
        auto_mix_state=auto_state,
        contexts={key: SimpleNamespace(player=player)},
        update_mix_trigger=lambda *_args, **_kwargs: updates.append(_args),
    )
    frame._resolve_mix_timing = lambda itm, overrides=None, effective_duration_override=None: MainFrame._resolve_mix_timing(
        frame, itm, overrides, effective_duration_override=effective_duration_override
    )
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-1",
        path=tmp_path / "a.wav",
        title="A",
        duration_seconds=12.0,
        cue_in_seconds=0.0,
        segue_seconds=5.0,
    )
    panel = SimpleNamespace(model=playlist)
    frame._start_next_from_playlist = lambda *args, **kwargs: True

    # backend trigger spóźniony: seconds > mix_at + guard, a jesteśmy blisko końca -> progress fallback powinien zadziałać
    frame._auto_mix_state_process(panel, item, SimpleNamespace(player=player), seconds=10.9, queued_selection=False)
    assert auto_state[key] is True
    assert key in frame._mix_plans and frame._mix_plans[key].triggered is True
    assert player.fade_calls and abs(player.fade_calls[0] - 1.1) < 1e-6  # remaining ~1.1s


def test_pfl_mix_preview_uses_mix_timing(tmp_path):
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    track_a = PlaylistItem(
        id="a",
        path=tmp_path / "a.wav",
        title="A",
        duration_seconds=10.0,
        cue_in_seconds=1.0,
        segue_seconds=3.0,  # mix_at = 4.0
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
    # effective_duration = duration - cue
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
    frame._measure_effective_duration = lambda _playlist, _item: 5.0  # override metadata (duration-cue = 9.0)

    ok = frame._preview_mix_with_next(playlist, track_a, overrides=None)
    assert ok is True
    _cur, _nxt, mix_at, pre_secs, fade_secs, eff, _next_cue = captured["args"]
    assert abs(mix_at - 4.0) < 1e-6  # cue 1.0 + (5.0 - fade 2.0)
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
    # stop_playlist mogło zostać wywołane wielokrotnie, ale co najmniej raz na daną playlistę
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
    assert started_indices == [2]  # po zatrzymaniu loop_hold kursor przesuwa się na kolejny element
    assert frame._auto_mix_tracker._last_item_id[playlist.id] == bed.id
    assert frame._last_started_item_id[playlist.id] == bed.id


def test_stop_playlist_clears_mix_plan_and_state(tmp_path):
    frame = MainFrame.__new__(MainFrame)
    frame._mix_plans = {("pl-1", "item-1"): None}
    frame._mix_trigger_points = {("pl-1", "item-1"): 5.0}
    frame._playback = SimpleNamespace(stop_playlist=lambda *_args, **_kwargs: [(( "pl-1","item-1"), None)], clear_auto_mix=lambda: None)
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
        contexts={( "pl-1","item-1"): None, ("pl-1","item-2"): None},
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


def _make_frame_for_automix(fade: float = 3.0) -> MainFrame:
    frame = MainFrame.__new__(MainFrame)
    frame._fade_duration = fade
    frame._mix_plans = {}
    frame._mix_trigger_points = {}
    frame._auto_mix_enabled = True
    frame._active_break_item = {}
    frame._state = AppState()
    frame._playlists = {}
    frame._auto_mix_tracker = AutoMixTracker()
    frame._last_started_item_id = {}
    playback = SimpleNamespace(auto_mix_state={}, contexts={})

    def _get_ctx(playlist_id: str):
        for key, ctx in playback.contexts.items():
            if key[0] == playlist_id:
                return key, ctx
        return None

    playback.get_context = _get_ctx  # type: ignore[attr-defined]
    frame._playback = playback
    frame._supports_mix_trigger = lambda _player=None: False
    return frame


def _register_playlist(frame: MainFrame, playlist: PlaylistModel, panel: object | None = None) -> None:
    if not hasattr(frame, "_state"):
        frame._state = AppState()
    frame._state.add_playlist(playlist)
    if not hasattr(frame, "_playlists"):
        frame._playlists = {}
    if panel is not None:
        frame._playlists[playlist.id] = panel  # type: ignore[attr-defined]


class _AutoMixPlayer(_DummyPlayer):
    def __init__(self, device_id: str, *, supports_mix_trigger: bool = False):
        super().__init__(device_id, supports=supports_mix_trigger)
        self.fade_calls: list[float] = []

    def fade_out(self, duration: float):
        self.fade_calls.append(duration)


def test_automix_prefers_segue_over_fallback(tmp_path):
    frame = _make_frame_for_automix(fade=3.0)
    started: list[dict] = []
    frame._start_next_from_playlist = lambda *_args, **kwargs: started.append(kwargs) or True

    playlist = PlaylistModel(id="pl-auto", name="Auto", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-segue",
        path=tmp_path / "podklad.wav",
        title="Podklad",
        duration_seconds=155.0,
        segue_seconds=150.0,  # explicit mix point near the end
    )
    playlist.add_items([item, PlaylistItem(id="next", path=tmp_path / "next.wav", title="Next", duration_seconds=10.0)])
    panel = SimpleNamespace(model=playlist)
    _register_playlist(frame, playlist, panel)
    player = _AutoMixPlayer("dev-1")
    ctx = SimpleNamespace(player=player)

    frame._auto_mix_state_process(panel, item, ctx, seconds=152.0, queued_selection=False)
    key = (playlist.id, item.id)
    assert frame._mix_plans[key].mix_at == 150.0
    assert frame._playback.auto_mix_state[key] is True
    # fade is capped to remaining time (155 - 151.5 = 3.5s)
    assert player.fade_calls == [pytest.approx(3.0, rel=0.01)]
    assert started, "Next track should be queued in automix sequence"


def test_automix_falls_back_to_global_fade_without_markers(tmp_path):
    frame = _make_frame_for_automix(fade=2.5)
    started: list[dict] = []
    frame._start_next_from_playlist = lambda *_args, **kwargs: started.append(kwargs) or True

    playlist = PlaylistModel(id="pl-fallback", name="Fallback", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-fallback",
        path=tmp_path / "no_markers.wav",
        title="No markers",
        duration_seconds=12.0,
    )
    playlist.add_items([item, PlaylistItem(id="after", path=tmp_path / "after.wav", title="After", duration_seconds=5.0)])
    panel = SimpleNamespace(model=playlist)
    _register_playlist(frame, playlist, panel)
    player = _AutoMixPlayer("dev-1")
    ctx = SimpleNamespace(player=player)

    # effective=12, fade=2.5 -> mix_at=9.5; simulate close to end
    frame._auto_mix_state_process(panel, item, ctx, seconds=10.5, queued_selection=False)
    key = (playlist.id, item.id)
    assert frame._mix_plans[key].mix_at == pytest.approx(9.5, rel=1e-3)
    assert frame._playback.auto_mix_state[key] is True
    # remaining time is 1.5s, so fade is trimmed to remaining
    assert player.fade_calls == [pytest.approx(1.5, rel=0.01)]
    assert started, "Automix should advance when only global fade is available"


def test_automix_waits_until_segue_point(tmp_path):
    frame = _make_frame_for_automix(fade=2.0)
    playlist = PlaylistModel(id="pl-wait", name="Wait", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-wait",
        path=tmp_path / "wait.wav",
        title="Wait",
        duration_seconds=20.0,
        segue_seconds=10.0,
    )
    playlist.add_items([item, PlaylistItem(id="next", path=tmp_path / "n.wav", title="Next", duration_seconds=5.0)])
    panel = SimpleNamespace(model=playlist)
    _register_playlist(frame, playlist, panel)
    player = _AutoMixPlayer("dev-1")
    ctx = SimpleNamespace(player=player)
    frame._playback.contexts[(playlist.id, item.id)] = ctx
    started: list[dict] = []
    frame._start_next_from_playlist = lambda *_a, **_k: started.append({}) or True

    frame._auto_mix_state_process(panel, item, ctx, seconds=8.5, queued_selection=False)
    assert started == []

    frame._auto_mix_state_process(panel, item, ctx, seconds=10.05, queued_selection=False)
    assert started, "Mix should fire only once the segue time is reached"


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
    frame._mix_plans = {(playlist.id, duplicate.id): MixPlan(mix_at=5.0, fade_seconds=1.0, base_cue=0.0, effective_duration=10.0, native_trigger=False)}
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
    assert refresh_calls, "Panel should refresh to reflect updated mix data"


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


def test_native_guard_handles_segue_near_track_end(tmp_path):
    frame = _make_frame_for_automix(fade=2.0)
    frame._supports_mix_trigger = lambda _player=None: True
    started: list[dict] = []
    frame._start_next_from_playlist = lambda *_args, **kwargs: started.append(kwargs) or True

    playlist = PlaylistModel(id="pl-native-tight", name="Native tight", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-tight",
        path=tmp_path / "tight.wav",
        title="Tight segue",
        duration_seconds=18.0,
        segue_seconds=17.98,
    )
    playlist.add_items(
        [
            item,
            PlaylistItem(id="next-tight", path=tmp_path / "next.wav", title="Next", duration_seconds=5.0),
        ]
    )
    panel = SimpleNamespace(model=playlist)
    _register_playlist(frame, playlist, panel)
    player = _AutoMixPlayer("dev-1", supports_mix_trigger=True)
    ctx = SimpleNamespace(player=player)

    frame._auto_mix_state_process(panel, item, ctx, seconds=5.0, queued_selection=False)
    key = (playlist.id, item.id)
    assert frame._mix_plans[key].native_trigger is True

    trigger_seconds = max(0.0, item.segue_seconds - 0.02)
    frame._auto_mix_state_process(panel, item, ctx, seconds=trigger_seconds, queued_selection=False)

    assert frame._playback.auto_mix_state[key] is True
    assert started, "Next track should start when native trigger cannot fire in time"
    remaining = max(0.0, item.duration_seconds - trigger_seconds)
    assert player.fade_calls == [pytest.approx(min(frame._fade_duration, remaining), rel=0.05)]


def test_native_guard_waits_until_shortfall_window(tmp_path):
    frame = _make_frame_for_automix(fade=2.5)
    frame._supports_mix_trigger = lambda _player=None: True
    started: list[dict] = []
    frame._start_next_from_playlist = lambda *_args, **kwargs: started.append(kwargs) or True

    playlist = PlaylistModel(id="pl-native-window", name="Native window", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-window",
        path=tmp_path / "window.wav",
        title="Guard window",
        duration_seconds=24.0,
        segue_seconds=23.8,
    )
    playlist.add_items(
        [
            item,
            PlaylistItem(id="next-window", path=tmp_path / "next2.wav", title="Next", duration_seconds=4.0),
        ]
    )
    panel = SimpleNamespace(model=playlist)
    _register_playlist(frame, playlist, panel)
    player = _AutoMixPlayer("dev-1", supports_mix_trigger=True)
    ctx = SimpleNamespace(player=player)

    frame._auto_mix_state_process(panel, item, ctx, seconds=6.0, queued_selection=False)
    key = (playlist.id, item.id)
    headroom = item.duration_seconds - item.segue_seconds
    fade_guard = min(MIX_NATIVE_LATE_GUARD, frame._fade_duration)
    shortfall = max(0.0, fade_guard - headroom)
    assert shortfall > 0.0

    early_seconds = max(0.0, item.segue_seconds - (shortfall + 0.05))
    frame._auto_mix_state_process(panel, item, ctx, seconds=early_seconds, queued_selection=False)
    assert key not in frame._playback.auto_mix_state
    assert started == []

    trigger_seconds = max(0.0, item.segue_seconds - max(0.0, shortfall / 2.0))
    frame._auto_mix_state_process(panel, item, ctx, seconds=trigger_seconds, queued_selection=False)
    assert frame._playback.auto_mix_state[key] is True
    assert len(started) == 1
    remaining = max(0.0, item.duration_seconds - trigger_seconds)
    assert player.fade_calls[-1] == pytest.approx(min(frame._fade_duration, remaining), rel=0.05)


def test_native_guard_respects_short_fade_window(tmp_path):
    frame = _make_frame_for_automix(fade=0.12)
    frame._supports_mix_trigger = lambda _player=None: True
    started: list[dict] = []
    frame._start_next_from_playlist = lambda *_args, **kwargs: started.append(kwargs) or True

    playlist = PlaylistModel(id="pl-native-fade", name="Native fade", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-fade",
        path=tmp_path / "fade.wav",
        title="Short fade guard",
        duration_seconds=40.0,
        segue_seconds=30.0,
    )
    playlist.add_items(
        [
            item,
            PlaylistItem(id="next-fade", path=tmp_path / "next3.wav", title="Next", duration_seconds=6.0),
        ]
    )
    panel = SimpleNamespace(model=playlist)
    _register_playlist(frame, playlist, panel)
    player = _AutoMixPlayer("dev-1", supports_mix_trigger=True)
    ctx = SimpleNamespace(player=player)

    before_mix = max(0.0, item.segue_seconds - 0.05)
    frame._auto_mix_state_process(panel, item, ctx, seconds=before_mix, queued_selection=False)
    assert started == []
    key = (playlist.id, item.id)
    assert key not in frame._playback.auto_mix_state

    within_guard = item.segue_seconds + 0.05
    frame._auto_mix_state_process(panel, item, ctx, seconds=within_guard, queued_selection=False)
    assert started == []
    assert key not in frame._playback.auto_mix_state

    beyond_guard = item.segue_seconds + 0.2
    frame._auto_mix_state_process(panel, item, ctx, seconds=beyond_guard, queued_selection=False)
    assert frame._playback.auto_mix_state[key] is True
    assert len(started) == 1
    remaining = max(0.0, item.duration_seconds - beyond_guard)
    assert player.fade_calls[-1] == pytest.approx(min(frame._fade_duration, remaining), rel=0.05)


def test_automix_respects_break_and_does_not_trigger(tmp_path):
    frame = _make_frame_for_automix(fade=2.0)
    frame._start_next_from_playlist = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Should not mix during break"))

    playlist = PlaylistModel(id="pl-break", name="Break", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-break",
        path=tmp_path / "break.wav",
        title="Break",
        duration_seconds=8.0,
    )
    item.break_after = True
    playlist.add_items([item])
    panel = SimpleNamespace(model=playlist)
    player = _AutoMixPlayer("dev-1")
    ctx = SimpleNamespace(player=player)

    frame._auto_mix_state_process(panel, item, ctx, seconds=7.0, queued_selection=False)
    key = (playlist.id, item.id)
    assert key not in frame._playback.auto_mix_state
    assert key not in frame._mix_plans or not getattr(frame._mix_plans.get(key), "triggered", False)
    assert player.fade_calls == []


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


def _prepare_saramix_playlist(tmp_path: Path) -> tuple[PlaylistModel, dict[str, PlaylistItem]]:
    src_m3u = Path(__file__).resolve().parents[1] / "logs" / "saramix.m3u"
    if not src_m3u.exists():
        pytest.skip("logs/saramix.m3u not available")
    entries: list[dict[str, object]] = []
    current_title: str | None = None
    current_duration: float | None = None
    for line in src_m3u.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#EXTM3U"):
            continue
        if stripped.startswith("#EXTINF:"):
            try:
                header, title = stripped.split(",", 1)
            except ValueError:
                header, title = stripped, ""
            try:
                current_duration = float(header[8:])
            except ValueError:
                current_duration = None
            current_title = title.strip() if title.strip() else None
            continue
        orig_path = Path(stripped)
        target = tmp_path / orig_path.name
        is_wybory = "Wybory" in orig_path.name
        if is_wybory:
            src_audio = Path(__file__).resolve().parents[1] / "POPARZENI KAWĄ TRZY - Wybory.flac"
            if src_audio.exists():
                shutil.copy(src_audio, target)
            else:
                target.write_text("wybory", encoding="utf-8")
        else:
            target.write_text("dummy", encoding="utf-8")
        entries.append({"path": target, "title": current_title, "duration": current_duration, "is_wybory": is_wybory})
        current_title = None
        current_duration = None

    playlist = PlaylistModel(id="pl-saramix", name="saramix", kind=PlaylistKind.MUSIC)
    items: dict[str, PlaylistItem] = {}

    def _key(name: str) -> str:
        return name.lower().replace(" ", "").replace("'", "").strip("[]")

    for idx, entry in enumerate(entries):
        path = entry["path"]
        duration_hint = float(entry.get("duration") or 0.0)
        metadata = None
        if entry.get("is_wybory"):
            metadata = extract_metadata(path)  # type: ignore[arg-type]
        title = (entry.get("title") or (metadata.title if metadata else None) or path.stem)  # type: ignore[arg-type]
        duration = (metadata.duration_seconds if metadata else None) or duration_hint
        item_kwargs = {
            "id": f"mix-{idx}",
            "path": path,
            "title": title,
            "duration_seconds": duration,
        }
        if metadata:
            item_kwargs.update(
                {
                    "artist": metadata.artist,
                    "replay_gain_db": metadata.replay_gain_db,
                    "cue_in_seconds": metadata.cue_in_seconds,
                    "segue_seconds": metadata.segue_seconds,
                    "overlap_seconds": metadata.overlap_seconds,
                    "intro_seconds": metadata.intro_seconds,
                    "outro_seconds": metadata.outro_seconds,
                    "loop_start_seconds": metadata.loop_start_seconds,
                    "loop_end_seconds": metadata.loop_end_seconds,
                    "loop_auto_enabled": metadata.loop_auto_enabled,
                    "loop_enabled": metadata.loop_enabled,
                }
            )
        item = PlaylistItem(**item_kwargs)  # type: ignore[arg-type]
        playlist.add_items([item])
        items[_key(item.title)] = item
        items[_key(item.path.stem)] = item
    return playlist, items


def test_saramix_mixpoint_wybory_prefers_segue(tmp_path):
    playlist, items = _prepare_saramix_playlist(tmp_path)
    wy_item = items.get("wybory")
    if wy_item is None:
        pytest.skip("Wybory track not found in saramix.m3u")

    if wy_item.segue_seconds is None:
        pytest.skip("Wybory does not expose a segue marker in metadata")
    frame = _make_frame_for_automix(fade=2.0)
    frame._start_next_from_playlist = lambda *_args, **_kwargs: True
    panel = SimpleNamespace(model=playlist)
    _register_playlist(frame, playlist, panel)
    player = _AutoMixPlayer("dev-1")
    ctx = SimpleNamespace(player=player)

    trigger_time = max(0.0, wy_item.segue_seconds + 0.3)
    frame._auto_mix_state_process(panel, wy_item, ctx, seconds=trigger_time, queued_selection=False)
    key = (playlist.id, wy_item.id)
    assert frame._mix_plans[key].mix_at == pytest.approx(wy_item.segue_seconds, rel=1e-3)
    assert frame._playback.auto_mix_state[key] is True
    remaining = max(0.0, wy_item.duration_seconds - trigger_time)
    assert player.fade_calls == [pytest.approx(min(frame._fade_duration, remaining), rel=0.05)]


def test_saramix_break_on_podklad_blocks_mix(tmp_path):
    playlist, items = _prepare_saramix_playlist(tmp_path)
    podklad = items.get("podklad")
    if podklad is None:
        pytest.skip("podklad track not found in saramix.m3u")

    podklad.break_after = True
    frame = _make_frame_for_automix(fade=2.5)
    frame._start_next_from_playlist = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Break should prevent automix"))
    panel = SimpleNamespace(model=playlist)
    _register_playlist(frame, playlist, panel)
    player = _AutoMixPlayer("dev-1")
    ctx = SimpleNamespace(player=player)

    frame._auto_mix_state_process(panel, podklad, ctx, seconds=max(0.0, podklad.duration_seconds - 1.0), queued_selection=False)
    key = (playlist.id, podklad.id)
    assert key not in frame._playback.auto_mix_state
    assert player.fade_calls == []
