from __future__ import annotations

import shutil
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Callable, Optional

import pytest

from sara.audio.engine import BackendType
from sara.core.config import SettingsManager
from sara.core.media_metadata import extract_metadata
from sara.core.mix_planner import (
    MIX_NATIVE_LATE_GUARD,
    MixPlan,
    clear_mix_plan,
    mark_mix_triggered,
    register_mix_plan,
    resolve_mix_timing,
)
from sara.core.playlist import PlaylistItem, PlaylistKind, PlaylistModel, PlaylistItemStatus
from sara.ui import mix_runtime
from sara.ui.playback_controller import PlaybackController


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
    mix_plans: dict[tuple[str, str], MixPlan] = {}
    mix_trigger_points: dict[tuple[str, str], float] = {}

    register_mix_plan(
        mix_plans,
        mix_trigger_points,
        "pl-1",
        "item-1",
        mix_at=5.0,
        fade_seconds=2.5,
        base_cue=1.0,
        effective_duration=9.0,
        native_trigger=True,
    )
    key = ("pl-1", "item-1")
    assert key in mix_plans
    assert mix_trigger_points[key] == 5.0
    assert mix_plans[key].fade_seconds == 2.5

    mark_mix_triggered(mix_plans, "pl-1", "item-1")
    assert mix_plans[key].triggered is True

    clear_mix_plan(mix_plans, mix_trigger_points, "pl-1", "item-1")
    assert mix_plans == {}
    assert mix_trigger_points == {}


def test_resolve_mix_timing_matches_editor_markers():
    fade_duration = 2.0
    item = PlaylistItem(
        id="i1",
        path=Path("x"),
        title="T",
        duration_seconds=11.0,
        cue_in_seconds=1.0,
        segue_seconds=3.0,
        overlap_seconds=None,
    )
    mix_at, fade, base_cue, effective = resolve_mix_timing(item, fade_duration)
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
    mix_at2, fade2, base_cue2, effective2 = resolve_mix_timing(item2, fade_duration)
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
    mix_at3, fade3, base_cue3, effective3 = resolve_mix_timing(item3, fade_duration)
    # brak markerów: użyj globalnego fade
    assert base_cue3 == 1.0
    assert effective3 == 10.0
    assert mix_at3 == 9.0  # 1 + (10 - fade(2))
    assert fade3 == 2.0


def test_resolve_mix_timing_honours_segue_fade_override():
    fade_duration = 2.0
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
    mix_at, fade, base_cue, effective = resolve_mix_timing(item, fade_duration)
    assert base_cue == 1.0
    assert effective == 11.0
    assert mix_at == pytest.approx(5.0, rel=1e-6)
    assert fade == pytest.approx(0.5, rel=1e-6)


class _MixHost:
    def __init__(self, *, fade: float = 3.0, auto_mix_enabled: bool = True) -> None:
        self._fade_duration = fade
        self._mix_plans: dict[tuple[str, str], MixPlan] = {}
        self._mix_trigger_points: dict[tuple[str, str], float] = {}
        self._auto_mix_enabled = auto_mix_enabled
        self._active_break_item: dict[str, str] = {}
        self._playback = SimpleNamespace(auto_mix_state={}, contexts={})

        self._start_next_from_playlist = lambda *_a, **_k: False
        self._playlist_has_selection = lambda _pid: False
        self._supports_mix_trigger = lambda _p=None: False
        self._auto_mix_now_from_callback = lambda *_a, **_k: None

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

    def _clear_mix_plan(self, playlist_id: str, item_id: str) -> None:
        clear_mix_plan(self._mix_plans, self._mix_trigger_points, playlist_id, item_id)

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

    def _auto_mix_state_process(self, panel, item: PlaylistItem, ctx, *, seconds: float, queued_selection: bool) -> None:
        mix_runtime.auto_mix_state_process(self, panel, item, ctx, seconds, queued_selection)

    def _auto_mix_now(self, playlist: PlaylistModel, item: PlaylistItem, panel) -> None:
        mix_runtime.auto_mix_now(self, playlist, item, panel)

    def _apply_mix_trigger_to_playback(self, *, playlist_id: str, item: PlaylistItem, panel) -> None:
        mix_runtime.apply_mix_trigger_to_playback(self, playlist_id=playlist_id, item=item, panel=panel)

    def _sync_loop_mix_trigger(self, *, panel, playlist: PlaylistModel, item: PlaylistItem, context) -> None:
        mix_runtime.sync_loop_mix_trigger(self, panel=panel, playlist=playlist, item=item, context=context)


class _AutoMixPlayer(_DummyPlayer):
    def __init__(self, device_id: str, *, supports_mix_trigger: bool = False):
        super().__init__(device_id, supports=supports_mix_trigger)
        self.fade_calls: list[float] = []

    def fade_out(self, duration: float):
        self.fade_calls.append(duration)


def test_progress_based_mix_triggers_when_native_missing(tmp_path):
    host = _MixHost(fade=3.0, auto_mix_enabled=True)
    host._supports_mix_trigger = lambda _p: False

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
    player = _AutoMixPlayer("dev-1")
    ctx = SimpleNamespace(player=player)

    started: list[dict] = []
    host._start_next_from_playlist = lambda *_a, **_k: started.append({}) or True

    # simulate progress near mix point (effective 12, overlap 3 -> mix_at 9)
    host._auto_mix_state_process(panel, item, ctx, seconds=9.1, queued_selection=False)
    key = (playlist.id, item.id)
    assert host._playback.auto_mix_state[key] is True
    assert host._mix_plans[key].triggered is True
    # fade should use min(fade, remaining)
    assert player.fade_calls and abs(player.fade_calls[0] - 2.9) < 1e-6  # remaining 2.9s
    assert started


def test_break_clears_mix_plan(tmp_path):
    host = _MixHost(fade=2.0, auto_mix_enabled=False)
    host._mix_plans = {("pl-1", "item-1"): MixPlan(mix_at=5.0, fade_seconds=2.0, base_cue=0.0, effective_duration=10.0, native_trigger=False)}
    host._mix_trigger_points = {("pl-1", "item-1"): 5.0}
    host._playback = SimpleNamespace(
        update_mix_trigger=lambda *_args, **_kwargs: True,
        contexts={},
        auto_mix_state={},
    )

    panel = SimpleNamespace(model=PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC))
    item = PlaylistItem(
        id="item-1",
        path=tmp_path / "a.wav",
        title="A",
        duration_seconds=10.0,
    )
    item.break_after = True
    host._apply_mix_trigger_to_playback(playlist_id="pl-1", item=item, panel=panel)
    assert host._mix_plans == {}
    assert host._mix_trigger_points == {}


def test_loop_hold_clears_mix_plan_and_sets_flag(tmp_path):
    host = _MixHost(fade=2.0, auto_mix_enabled=False)
    host._mix_plans = {("pl-1", "item-1"): MixPlan(mix_at=5.0, fade_seconds=2.0, base_cue=0.0, effective_duration=10.0, native_trigger=False)}
    host._mix_trigger_points = {("pl-1", "item-1"): 5.0}
    auto_state: dict = {}
    host._playback = SimpleNamespace(
        auto_mix_state=auto_state,
        update_mix_trigger=lambda *_args, **_kwargs: True,
    )
    host._supports_mix_trigger = lambda _p: False

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
    host._sync_loop_mix_trigger(panel=None, playlist=playlist, item=item, context=context)
    assert ("pl-1", "item-1") not in host._mix_trigger_points
    assert auto_state[("pl-1", "item-1")] == "loop_hold"


def test_loop_hold_in_automix_does_not_auto_advance(tmp_path):
    host = _MixHost(fade=1.5, auto_mix_enabled=True)
    host._mix_plans = {("pl-1", "item-1"): MixPlan(mix_at=4.0, fade_seconds=1.5, base_cue=0.0, effective_duration=10.0, native_trigger=False)}
    host._mix_trigger_points = {("pl-1", "item-1"): 4.0}
    auto_state: dict = {}
    host._playback = SimpleNamespace(
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
    context = SimpleNamespace(player=_DummyPlayer("dev-1"))
    auto_next_calls: list[object] = []
    host._auto_mix_play_next = lambda *_a, **_k: auto_next_calls.append(object())

    host._sync_loop_mix_trigger(panel=panel, playlist=playlist, item=item, context=context)

    assert auto_state[("pl-1", "item-1")] == "loop_hold"
    assert ("pl-1", "item-1") not in host._mix_trigger_points
    assert auto_next_calls == []


def test_auto_mix_state_process_skips_loop_hold(tmp_path):
    host = _MixHost(fade=2.0, auto_mix_enabled=True)
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
    key = (playlist.id, item.id)
    player = _AutoMixPlayer("dev-1")
    ctx = SimpleNamespace(player=player)
    host._playback.auto_mix_state[key] = "loop_hold"
    host._playback.contexts[key] = ctx
    started: list[dict] = []
    host._start_next_from_playlist = lambda *_a, **_k: started.append({}) or True

    host._auto_mix_state_process(panel, item, ctx, seconds=5.0, queued_selection=False)

    assert started == []
    assert player.fade_calls == []
    assert host._playback.auto_mix_state[key] == "loop_hold"


def test_early_native_trigger_reschedules_mix_point(tmp_path):
    host = _MixHost(fade=2.0, auto_mix_enabled=True)
    key = ("pl-1", "item-1")
    host._mix_plans = {
        key: MixPlan(mix_at=8.0, fade_seconds=2.0, base_cue=0.0, effective_duration=12.0, native_trigger=True, triggered=False)
    }
    host._mix_trigger_points = {key: 8.0}
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
    host._supports_mix_trigger = lambda _p: True
    host._playlist_has_selection = lambda _pid: False
    host._playback = SimpleNamespace(
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
    host._auto_mix_now(playlist, item, panel)
    assert update_calls and update_calls[0][2] is None
    assert host._mix_plans[key].native_trigger is False
    assert host._mix_plans[key].mix_at == pytest.approx(8.0, rel=1e-3)
    assert host._mix_plans[key].triggered is False
    assert host._playback.auto_mix_state == {}


def test_native_fallback_triggers_progress_mix(tmp_path):
    host = _MixHost(fade=2.0, auto_mix_enabled=True)
    host._supports_mix_trigger = lambda _p: True
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

    host._playback = SimpleNamespace(
        auto_mix_state={},
        contexts={key: SimpleNamespace(player=player)},
        update_mix_trigger=_record_update,
    )
    host._mix_plans[key] = MixPlan(
        mix_at=15.0,
        fade_seconds=host._fade_duration,
        base_cue=0.0,
        effective_duration=item.effective_duration_seconds,
        native_trigger=True,
    )
    host._mix_trigger_points[key] = 15.0
    started: list[dict] = []
    host._start_next_from_playlist = lambda *_a, **_k: started.append({}) or True

    # Backend strzelił za wcześnie – przejdź na fallback progresowy
    host._auto_mix_now(playlist, item, panel)
    assert update_calls and update_calls[-1][2] is None
    assert host._mix_plans[key].native_trigger is False

    ctx = host._playback.contexts[key]
    host._auto_mix_state_process(panel, item, ctx, seconds=15.2, queued_selection=False)
    assert started, "Fallback progresowy powinien wystartować miks"


def test_manual_selection_triggers_mix_when_auto_mix_disabled(tmp_path):
    host = _MixHost(fade=2.0, auto_mix_enabled=False)
    auto_state = {}
    host._playback = SimpleNamespace(auto_mix_state=auto_state, contexts={})
    host._supports_mix_trigger = lambda _p: False

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
    host._start_next_from_playlist = lambda *args, **kwargs: True
    host._playlist_has_selection = lambda _pid: True

    host._auto_mix_state_process(panel, item, ctx, seconds=9.0, queued_selection=True)
    key = (playlist.id, item.id)
    assert auto_state[key] is True
    assert host._mix_plans[key].triggered is True
    assert player.fade_calls and abs(player.fade_calls[0] - 1.0) < 1e-6  # remaining 1s


def test_late_native_trigger_falls_back_to_progress(tmp_path):
    host = _MixHost(fade=2.0, auto_mix_enabled=True)
    key = ("pl-1", "item-1")
    host._mix_trigger_points = {key: 5.0}
    auto_state = {}

    class _LatePlayer(_DummyPlayer):
        def __init__(self):
            super().__init__("dev-1", supports=True)
            self.fade_calls: list[float] = []

        def fade_out(self, duration: float):
            self.fade_calls.append(duration)

        def get_length_seconds(self):
            return 12.0

    player = _LatePlayer()
    host._supports_mix_trigger = lambda _p: True
    host._playback = SimpleNamespace(
        auto_mix_state=auto_state,
        contexts={key: SimpleNamespace(player=player)},
        update_mix_trigger=lambda *_args, **_kwargs: True,
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
    host._start_next_from_playlist = lambda *args, **kwargs: True

    # backend trigger spóźniony: seconds > mix_at + guard, a jesteśmy blisko końca -> progress fallback powinien zadziałać
    host._auto_mix_state_process(panel, item, SimpleNamespace(player=player), seconds=10.9, queued_selection=False)
    assert auto_state[key] is True
    assert key in host._mix_plans and host._mix_plans[key].triggered is True
    assert player.fade_calls and abs(player.fade_calls[0] - 1.1) < 1e-6  # remaining ~1.1s


def test_automix_prefers_segue_over_fallback(tmp_path):
    host = _MixHost(fade=3.0, auto_mix_enabled=True)
    started: list[dict] = []
    host._start_next_from_playlist = lambda *_args, **kwargs: started.append(kwargs) or True

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
    player = _AutoMixPlayer("dev-1")
    ctx = SimpleNamespace(player=player)

    host._auto_mix_state_process(panel, item, ctx, seconds=152.0, queued_selection=False)
    key = (playlist.id, item.id)
    assert host._mix_plans[key].mix_at == 150.0
    assert host._playback.auto_mix_state[key] is True
    # fade is capped to remaining time
    assert player.fade_calls == [pytest.approx(3.0, rel=0.01)]
    assert started, "Next track should be queued in automix sequence"


def test_automix_falls_back_to_global_fade_without_markers(tmp_path):
    host = _MixHost(fade=2.5, auto_mix_enabled=True)
    started: list[dict] = []
    host._start_next_from_playlist = lambda *_args, **kwargs: started.append(kwargs) or True

    playlist = PlaylistModel(id="pl-fallback", name="Fallback", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-fallback",
        path=tmp_path / "no_markers.wav",
        title="No markers",
        duration_seconds=12.0,
    )
    playlist.add_items([item, PlaylistItem(id="after", path=tmp_path / "after.wav", title="After", duration_seconds=5.0)])
    panel = SimpleNamespace(model=playlist)
    player = _AutoMixPlayer("dev-1")
    ctx = SimpleNamespace(player=player)

    # fade triggers near the end (12 - 2.5 = 9.5)
    host._auto_mix_state_process(panel, item, ctx, seconds=10.0, queued_selection=False)
    key = (playlist.id, item.id)
    assert host._mix_plans[key].mix_at == pytest.approx(9.5, rel=1e-6)
    assert host._playback.auto_mix_state[key] is True
    assert started
    assert player.fade_calls


def test_automix_waits_until_segue_point(tmp_path):
    host = _MixHost(fade=2.0, auto_mix_enabled=True)
    started: list[dict] = []
    host._start_next_from_playlist = lambda *_args, **kwargs: started.append(kwargs) or True

    playlist = PlaylistModel(id="pl-wait", name="Wait", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item",
        path=tmp_path / "seg.wav",
        title="Segue",
        duration_seconds=10.0,
        segue_seconds=7.0,
    )
    playlist.add_items([item, PlaylistItem(id="next", path=tmp_path / "next.wav", title="Next", duration_seconds=5.0)])
    panel = SimpleNamespace(model=playlist)
    player = _AutoMixPlayer("dev-1")
    ctx = SimpleNamespace(player=player)

    host._auto_mix_state_process(panel, item, ctx, seconds=6.0, queued_selection=False)
    assert started == []
    assert player.fade_calls == []

    host._auto_mix_state_process(panel, item, ctx, seconds=7.1, queued_selection=False)
    assert started


def test_native_guard_handles_segue_near_track_end(tmp_path):
    host = _MixHost(fade=1.0, auto_mix_enabled=True)
    host._supports_mix_trigger = lambda _p: True
    started: list[dict] = []
    host._start_next_from_playlist = lambda *_args, **kwargs: started.append(kwargs) or True

    playlist = PlaylistModel(id="pl-guard", name="Guard", kind=PlaylistKind.MUSIC)
    # cue=0, duration=5, segue=4.9 -> headroom after mix = 0.1
    item = PlaylistItem(
        id="item",
        path=tmp_path / "x.wav",
        title="X",
        duration_seconds=5.0,
        segue_seconds=4.9,
    )
    playlist.add_items([item])
    panel = SimpleNamespace(model=playlist)
    player = _AutoMixPlayer("dev-1", supports_mix_trigger=True)
    ctx = SimpleNamespace(player=player)

    key = (playlist.id, item.id)
    host._playback.contexts[key] = ctx

    # We should still trigger around segue point even with tiny headroom (guard window shrinks)
    host._auto_mix_state_process(panel, item, ctx, seconds=4.95, queued_selection=False)
    assert started
    assert player.fade_calls


def test_native_guard_waits_until_shortfall_window(tmp_path):
    host = _MixHost(fade=2.5, auto_mix_enabled=True)
    host._supports_mix_trigger = lambda _p: True
    started: list[dict] = []
    host._start_next_from_playlist = lambda *_args, **kwargs: started.append(kwargs) or True

    playlist = PlaylistModel(id="pl-native-window", name="Native window", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item-window",
        path=tmp_path / "window.wav",
        title="Guard window",
        duration_seconds=24.0,
        segue_seconds=23.8,
    )
    playlist.add_items([item, PlaylistItem(id="next-window", path=tmp_path / "next2.wav", title="Next", duration_seconds=4.0)])
    panel = SimpleNamespace(model=playlist)
    player = _AutoMixPlayer("dev-1", supports_mix_trigger=True)
    ctx = SimpleNamespace(player=player)
    key = (playlist.id, item.id)
    host._playback.contexts[key] = ctx

    host._auto_mix_state_process(panel, item, ctx, seconds=6.0, queued_selection=False)
    assert host._mix_plans[key].native_trigger is True

    headroom = item.duration_seconds - item.segue_seconds
    fade_guard = min(MIX_NATIVE_LATE_GUARD, host._fade_duration)
    shortfall = max(0.0, fade_guard - headroom)
    assert shortfall > 0.0

    early_seconds = max(0.0, item.segue_seconds - (shortfall + 0.05))
    host._auto_mix_state_process(panel, item, ctx, seconds=early_seconds, queued_selection=False)
    assert key not in host._playback.auto_mix_state
    assert started == []

    trigger_seconds = max(0.0, item.segue_seconds - max(0.0, shortfall / 2.0))
    host._auto_mix_state_process(panel, item, ctx, seconds=trigger_seconds, queued_selection=False)
    assert host._playback.auto_mix_state[key] is True
    assert len(started) == 1
    remaining = max(0.0, item.duration_seconds - trigger_seconds)
    assert player.fade_calls[-1] == pytest.approx(min(host._fade_duration, remaining), rel=0.05)


def test_native_guard_respects_short_fade_window(tmp_path):
    host = _MixHost(fade=0.12, auto_mix_enabled=True)
    host._supports_mix_trigger = lambda _p: True
    started: list[dict] = []
    host._start_next_from_playlist = lambda *_args, **kwargs: started.append(kwargs) or True

    playlist = PlaylistModel(id="pl-native-fade", name="Native fade", kind=PlaylistKind.MUSIC)
    item = PlaylistItem(
        id="item",
        path=tmp_path / "fade.wav",
        title="Short fade guard",
        duration_seconds=40.0,
        segue_seconds=30.0,
    )
    playlist.add_items([item, PlaylistItem(id="next-fade", path=tmp_path / "next3.wav", title="Next", duration_seconds=6.0)])
    panel = SimpleNamespace(model=playlist)
    player = _AutoMixPlayer("dev-1", supports_mix_trigger=True)
    ctx = SimpleNamespace(player=player)
    key = (playlist.id, item.id)
    host._playback.contexts[key] = ctx

    before_mix = max(0.0, item.segue_seconds - 0.05)
    host._auto_mix_state_process(panel, item, ctx, seconds=before_mix, queued_selection=False)
    assert started == []
    assert key not in host._playback.auto_mix_state

    within_guard = item.segue_seconds + 0.05
    host._auto_mix_state_process(panel, item, ctx, seconds=within_guard, queued_selection=False)
    assert started == []
    assert key not in host._playback.auto_mix_state

    beyond_guard = item.segue_seconds + 0.2
    host._auto_mix_state_process(panel, item, ctx, seconds=beyond_guard, queued_selection=False)
    assert host._playback.auto_mix_state[key] is True
    assert len(started) == 1
    remaining = max(0.0, item.duration_seconds - beyond_guard)
    assert player.fade_calls[-1] == pytest.approx(min(host._fade_duration, remaining), rel=0.05)


def test_automix_respects_break_and_does_not_trigger(tmp_path):
    host = _MixHost(fade=2.0, auto_mix_enabled=True)
    host._start_next_from_playlist = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Should not mix during break"))

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

    host._auto_mix_state_process(panel, item, ctx, seconds=7.0, queued_selection=False)
    key = (playlist.id, item.id)
    assert key not in host._playback.auto_mix_state
    assert key not in host._mix_plans or not host._mix_plans.get(key).triggered
    assert player.fade_calls == []


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
    host = _MixHost(fade=2.0, auto_mix_enabled=True)
    host._start_next_from_playlist = lambda *_args, **_kwargs: True
    panel = SimpleNamespace(model=playlist)
    player = _AutoMixPlayer("dev-1")
    ctx = SimpleNamespace(player=player)

    trigger_time = max(0.0, wy_item.segue_seconds + 0.3)
    host._auto_mix_state_process(panel, wy_item, ctx, seconds=trigger_time, queued_selection=False)
    key = (playlist.id, wy_item.id)
    assert host._mix_plans[key].mix_at == pytest.approx(wy_item.segue_seconds, rel=1e-3)
    assert host._playback.auto_mix_state[key] is True
    remaining = max(0.0, wy_item.duration_seconds - trigger_time)
    assert player.fade_calls == [pytest.approx(min(host._fade_duration, remaining), rel=0.05)]


def test_saramix_break_on_podklad_blocks_mix(tmp_path):
    playlist, items = _prepare_saramix_playlist(tmp_path)
    podklad = items.get("podklad")
    if podklad is None:
        pytest.skip("podklad track not found in saramix.m3u")

    podklad.break_after = True
    host = _MixHost(fade=2.5, auto_mix_enabled=True)
    host._start_next_from_playlist = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Break should prevent automix"))
    panel = SimpleNamespace(model=playlist)
    player = _AutoMixPlayer("dev-1")
    ctx = SimpleNamespace(player=player)

    host._auto_mix_state_process(panel, podklad, ctx, seconds=max(0.0, podklad.duration_seconds - 1.0), queued_selection=False)
    key = (playlist.id, podklad.id)
    assert key not in host._playback.auto_mix_state
    assert player.fade_calls == []
