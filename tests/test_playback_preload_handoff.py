"""Regresja: rzeczywisty fabryczny player, kolejka ręczna i wolne otwarcie."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sara.audio.bass.player.base import BassPlayer
from sara.audio.engine import AudioEngine, AudioDevice, BackendType
from sara.core.config import SettingsManager
from sara.core.playlist import PlaylistItem, PlaylistModel, PlaylistKind
from sara.ui.controllers.playback.start import start_playback
from sara.ui.playback.controller import PlaybackController


class SlowManager:
    def __init__(self):
        self.created = []
        self.freed = []
        self.played = []
        self.volumes = {}
        self.positions = {}
        self.loops = {}
        self.block = None
        self.entered = threading.Event()

    def acquire_device(self, index):
        return SimpleNamespace(release=lambda: None)

    def stream_create_file(self, index, path, **kwargs):
        self.created.append((index, path, threading.current_thread().name))
        if path.name == 'bed.mp3':
            self.entered.set()
            if self.block:
                assert self.block.wait(5)
            time.sleep(0.12)
        return len(self.created)

    def stream_free(self, stream):
        self.freed.append(stream)

    def channel_set_volume(self, stream, value):
        self.volumes[stream] = value

    def channel_set_position(self, stream, seconds):
        self.positions[stream] = seconds

    def channel_play(self, stream, restart):
        self.played.append(stream)

    def channel_stop(self, stream):
        pass

    def channel_get_length_seconds(self, stream):
        return 3420.0

    def channel_clear_loop_points(self, stream):
        pass

    def channel_set_looping(self, stream, enabled):
        pass

    def channel_set_loop_points(self, stream, start, end):
        self.loops[stream] = (start, end)

    def seconds_to_bytes(self, stream, seconds):
        return int(seconds * 176400)

    def channel_remove_sync(self, stream, handle):
        pass


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.delenv('SARA_ENABLE_PRELOAD', raising=False)
    manager = SlowManager()
    engine = AudioEngine.__new__(AudioEngine)
    engine._devices = {f'bass:{i}': AudioDevice(id=f'bass:{i}', name=str(i), backend=BackendType.BASS, raw_index=i) for i in (1, 2)}
    engine._players = {}

    def make(device):
        player = BassPlayer(manager, device.raw_index)
        player._start_monitor = lambda: None
        return player

    engine._providers = [SimpleNamespace(backend=BackendType.BASS, create_player=make)]
    controller = PlaybackController(engine, SettingsManager(config_path=tmp_path / 'settings.yaml'), lambda *_: None)
    playlist = PlaylistModel(id='pl', name='muza', kind=PlaylistKind.MUSIC)
    playlist.set_output_slots(['bass:1', 'bass:2'])
    items = []
    for name in ['intro.wav', 'bed.mp3', 'other.wav']:
        path = tmp_path / name
        path.write_bytes(b'fixture')
        items.append(PlaylistItem(id=name, path=path, title=name, duration_seconds=3420, is_selected=True))
    items[1].loop_enabled = True
    items[1].loop_start_seconds = 0.0
    items[1].loop_end_seconds = 3413.235
    items[1].replay_gain_db = -6.0
    playlist.add_items(items)
    frame = SimpleNamespace(
        _playback=controller, _stop_preview=lambda: None, _auto_mix_enabled=False,
        _fade_duration=0.0, _focus_playing_track=False, _active_break_item={},
        _get_playback_context=controller.get_context, _supports_mix_trigger=lambda p: False,
        _stop_playlist_playback=Mock(), _resolve_mix_timing=lambda *a, **k: (None, 0.0, 0.0, 3420.0),
        _register_mix_plan=Mock(), _adjust_duration_and_mix_trigger=Mock(), _focus_lock={},
        _last_started_item_id={}, _sync_loop_mix_trigger=Mock(), _maybe_focus_playing_item=Mock(),
        _announce_event=Mock(),
    )
    panel = SimpleNamespace(model=playlist, update_item_display=Mock())
    yield SimpleNamespace(manager=manager, engine=engine, controller=controller, playlist=playlist,
                         items=items, frame=frame, panel=panel)
    if manager.block:
        manager.block.set()
    close = getattr(controller, 'close_preloads', None)
    if close:
        close()
    if controller._preload_executor:
        controller._preload_executor.shutdown(wait=True)
    engine.stop_all()


def drain(rig):
    executor = rig.controller._preload_executor
    if executor:
        executor.submit(lambda: None).result(timeout=5)


@pytest.mark.parametrize('automix', [False, True])
def test_mix_start_reuses_prepared_factory_player_without_slow_open(rig, automix):
    rig.frame._auto_mix_enabled = automix
    assert start_playback(rig.frame, rig.panel, rig.items[0], auto_mix_sequence=automix)
    drain(rig)
    t = time.perf_counter()
    assert start_playback(rig.frame, rig.panel, rig.items[1], auto_mix_sequence=automix, prefer_overlap=True)
    elapsed = time.perf_counter() - t
    assert elapsed < 0.1, f'Synchroniczne otwarcie przy miksie: {elapsed:.3f}s'
    opens = [entry for entry in rig.manager.created if entry[1] == rig.items[1].path]
    assert len(opens) == 1
    assert opens[0][2].startswith('sara-preload')
    player = rig.controller.contexts[('pl', 'bed.mp3')].player
    assert rig.manager.volumes[player._stream] == pytest.approx(10 ** (-6 / 20))
    assert rig.manager.loops[player._stream] == (0, int(3413.235 * 176400))


def test_repeated_schedule_keeps_same_prepared_stream(rig):
    rig.controller.schedule_next_preload(rig.playlist, current_item_id=rig.items[0].id)
    drain(rig)
    before = len(rig.manager.created)
    rig.controller.schedule_next_preload(rig.playlist, current_item_id=rig.items[0].id)
    drain(rig)
    assert len(rig.manager.created) == before


def test_stop_during_preload_releases_late_stream_without_waiting(rig):
    rig.manager.block = threading.Event()
    rig.items[0].is_selected = False
    rig.controller.schedule_next_preload(rig.playlist, current_item_id=rig.items[0].id)
    assert rig.manager.entered.wait(2)
    t = time.perf_counter()
    rig.controller.stop_playlist(rig.playlist.id)
    assert time.perf_counter() - t < 0.1
    rig.manager.block.set()
    drain(rig)
    assert rig.manager.freed == [1]
    assert not rig.manager.played


def test_preload_does_not_replace_or_mutate_active_or_pfl_player(rig):
    rig.playlist.set_output_slots(['bass:2'])
    active = rig.engine.create_player('bass:2')
    active.play('on-air', str(rig.items[2].path))
    active.set_gain_db(-9)
    before = (active._stream, active._gain_factor, dict(rig.manager.volumes))
    rig.controller.schedule_next_preload(rig.playlist, current_item_id=rig.items[0].id)
    drain(rig)
    assert rig.engine._players['bass:2'] is active
    assert (active._stream, active._gain_factor) == before[:2]
    assert rig.manager.volumes[active._stream] == before[2][active._stream]


def test_changed_queue_frees_obsolete_preload(rig):
    rig.items[0].is_selected = False
    rig.controller.schedule_next_preload(rig.playlist, current_item_id=rig.items[0].id)
    drain(rig)
    rig.items[1].is_selected = False
    rig.controller.schedule_next_preload(rig.playlist, current_item_id=rig.items[0].id)
    drain(rig)
    assert rig.manager.freed == [1]


def test_automix_prepares_played_item_on_wrap(rig):
    from sara.core.playlist import PlaylistItemStatus
    rig.frame._auto_mix_enabled = True
    rig.items[0].status = PlaylistItemStatus.PLAYED
    rig.items[1].status = PlaylistItemStatus.PLAYED
    assert start_playback(rig.frame, rig.panel, rig.items[2], auto_mix_sequence=True)
    drain(rig)
    assert rig.controller.preloaded_paths() == [rig.items[0].path]


def test_queue_change_during_playback_reschedules(rig):
    from sara.ui.controllers.playlists.focus import on_toggle_selection
    assert start_playback(rig.frame, rig.panel, rig.items[0])
    drain(rig)
    rig.frame._get_playlist_model = lambda pid: rig.playlist
    rig.frame._playlists = {}
    # Usuń podkład z kolejki: zostaje third, zmiana nie dotyka grającego intro.
    active = rig.controller.contexts[('pl', 'intro.wav')].player
    stream = active._stream
    on_toggle_selection(rig.frame, 'pl', 'bed.mp3')
    drain(rig)
    assert rig.controller.preloaded_paths() == [rig.items[2].path]
    assert active._stream == stream


def test_inflight_preload_is_not_waited_for_by_handoff(rig):
    rig.manager.block = threading.Event()
    rig.items[0].is_selected = False
    rig.controller.schedule_next_preload(rig.playlist, current_item_id=rig.items[0].id)
    assert rig.manager.entered.wait(2)
    t = time.perf_counter()
    assert rig.controller._take_preloaded_player('pl', 'bass:1') is None
    assert time.perf_counter() - t < 0.1
    rig.manager.block.set()
    drain(rig)
    assert rig.manager.freed == [1]


@pytest.mark.parametrize('change', ['path', 'cue', 'loop', 'device'])
def test_changed_request_cannot_consume_wrong_stream(rig, change):
    rig.items[0].is_selected = False
    rig.controller.schedule_next_preload(rig.playlist, current_item_id=rig.items[0].id)
    drain(rig)
    item = rig.items[1]
    if change == 'path':
        item.path = rig.items[2].path
    elif change == 'cue':
        item.cue_in_seconds = 1.25
    elif change == 'loop':
        item.loop_enabled = False
    else:
        rig.playlist.set_output_slots(['bass:2'])
    result = rig.controller.start_item(rig.playlist, item, start_seconds=item.cue_in_seconds or 0,
                                       on_finished=lambda *a:None, on_progress=lambda *a:None)
    drain(rig)
    assert result.player._stream != 1
    assert 1 in rig.manager.freed
    assert rig.manager.created[-1][1] == item.path
    if change == 'cue':
        assert rig.manager.positions[result.player._stream] == 1.25


def test_close_releases_ready_preload_and_cannot_reschedule(rig):
    rig.controller.schedule_next_preload(rig.playlist, current_item_id=rig.items[0].id)
    drain(rig)
    rig.controller.close_preloads()
    rig.controller._preload_executor.shutdown(wait=True)
    rig.controller.schedule_next_preload(rig.playlist, current_item_id=rig.items[0].id)
    assert rig.manager.freed == [1]
    assert rig.controller.preloaded_paths() == []


def test_selection_change_during_automix_keeps_sequence(rig):
    from sara.ui.controllers.playlists.focus import on_toggle_selection
    rig.frame._auto_mix_enabled = True
    rig.frame._get_playlist_model = lambda pid: rig.playlist
    rig.frame._playlists = {}
    rig.items[1].is_selected = False
    rig.items[2].is_selected = False
    assert start_playback(rig.frame, rig.panel, rig.items[0], auto_mix_sequence=True)
    drain(rig)
    on_toggle_selection(rig.frame, 'pl', 'other.wav')
    drain(rig)
    assert rig.items[2].is_selected is False  # istniejąca blokada ręcznej kolejki w automiksie
    assert rig.controller.preloaded_paths() == [rig.items[1].path]


def test_disabling_automix_prepares_manual_candidate(rig):
    from sara.ui.controllers.playback.automix import set_auto_mix_enabled
    rig.frame._auto_mix_enabled = True
    rig.frame._get_playlist_model = lambda pid: rig.playlist
    rig.items[1].is_selected = False
    assert start_playback(rig.frame, rig.panel, rig.items[0], auto_mix_sequence=True)
    drain(rig)
    set_auto_mix_enabled(rig.frame, False)
    drain(rig)
    assert rig.controller.preloaded_paths() == [rig.items[2].path]
