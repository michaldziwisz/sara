from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mutagen.apev2 import APEv2

from sara.core import loudness
from sara.core.app_state import AppState, PlaylistFactory
from sara.core.config import SettingsManager
from sara.core.media_metadata import extract_metadata, save_replay_gain_metadata
from sara.core.playlist import PlaylistKind
from sara.ui.controllers.playlists import item_loading


XML = 'noise\b<bs1770gain><track><integrated lufs="-30"/><true-peak tpfs="-2" amplitude="0.79"/></track></bs1770gain>'
MARKER = 'EBU R128;I=-30.00;TP=-2.00;target=-23;gain=+1.00'


def make_frame(tmp_path):
    settings = SettingsManager(tmp_path / 'settings.yaml')
    frame = SimpleNamespace(
        _settings=settings, _state=AppState(), _playlist_factory=PlaylistFactory(),
        _playback=SimpleNamespace(contexts={}, preview_context=None),
        _audio_engine=SimpleNamespace(_players={}), _announce_event=Mock(),
    )
    frame._metadata_worker_count = item_loading.metadata_worker_count
    frame._load_playlist_item = lambda p, e=None: item_loading.load_playlist_item(frame, p, e)
    frame._load_items_from_sources = lambda s: item_loading.load_items_from_sources(frame, s)
    return frame


def add_tracks(frame, tmp_path, count=1, kind=PlaylistKind.MUSIC):
    paths = [tmp_path / f'{kind.value}-{i}.mp3' for i in range(count)]
    for path in paths:
        path.write_bytes(b'fixture')
    items = item_loading.create_items_from_paths(frame, paths)
    model = frame._playlist_factory.create_playlist('Lista', kind=kind, items=items)
    frame._state.add_playlist(model)
    return model


@pytest.fixture
def harness(tmp_path, monkeypatch):
    from sara.ui.services import auto_loudness
    frame = make_frame(tmp_path)
    callbacks = queue.Queue()
    calls = []
    monkeypatch.setattr(loudness, 'find_bs1770gain', lambda: Path('bs1770gain'))

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs, threading.get_ident()))
        return SimpleNamespace(returncode=0, stdout=XML, stderr='')

    monkeypatch.setattr(loudness.subprocess, 'run', run)
    service = auto_loudness.AutoLoudnessService(frame, call_after=lambda fn, *args: callbacks.put((fn, args)))
    frame._auto_loudness = service

    def drain(predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                fn, args = callbacks.get(timeout=0.01)
                fn(*args)
            except queue.Empty:
                pass
            service.poll()
            if predicate():
                return
        assert predicate(), 'Nie otrzymano wyniku kolejki'

    yield frame, service, calls, drain
    service.close()


def test_three_files_are_measured_off_gui_and_persisted(harness, tmp_path):
    frame, service, calls, drain = harness
    model = add_tracks(frame, tmp_path, 3)
    main_thread = threading.get_ident()
    service.poll()
    drain(lambda: all(i.sara_loudness for i in model.items))
    assert len(calls) == 3
    assert len({call[2] for call in calls}) == 1
    assert all(call[2] != main_thread for call in calls)
    for item in model.items:
        assert item.replay_gain_db == 1.0
        tags = APEv2(item.path)
        assert str(tags['REPLAYGAIN_TRACK_GAIN']) == '+1.00 dB'
        assert str(tags['SARA_LOUDNESS']) == MARKER
        assert extract_metadata(item.path).sara_loudness == MARKER
    frame._announce_event.assert_not_called()


def test_marker_skips_measurement_including_m3u_reload(harness, tmp_path):
    frame, service, calls, drain = harness
    model = add_tracks(frame, tmp_path)
    path = model.items[0].path
    assert save_replay_gain_metadata(path, 1.0, sara_loudness=MARKER)
    entries = [{'path': str(path)}]
    model.items = item_loading.create_items_from_m3u_entries(frame, entries)
    service.poll()
    drain(lambda: True)
    model.items = item_loading.create_items_from_m3u_entries(frame, entries)
    service.poll()
    drain(lambda: True)
    assert calls == []
    assert model.items[0].replay_gain_db == 1.0


def test_foreign_gain_is_replaced_and_duplicate_paths_propagate(harness, tmp_path):
    frame, service, calls, drain = harness
    model = add_tracks(frame, tmp_path)
    item = model.items[0]
    save_replay_gain_metadata(item.path, 9.0)
    other = frame._playlist_factory.create_playlist('Druga', items=item_loading.create_items_from_paths(frame, [item.path]))
    frame._state.add_playlist(other)
    assert other.items[0].replay_gain_db == 9.0
    service.poll()
    drain(lambda: bool(item.sara_loudness))
    assert len(calls) == 1
    assert item.replay_gain_db == other.items[0].replay_gain_db == 1.0
    # Nowa kopia tej samej ścieżki po zakończeniu kolejki też dziedziczy wynik.
    other.items = item_loading.create_items_from_paths(frame, [item.path])
    service.poll()
    assert other.items[0].replay_gain_db == 1.0
    assert len(calls) == 1


@pytest.mark.parametrize('busy', ['playing', 'paused', 'preloaded', 'prepared_controller', 'preview', 'stream_without_context'])
def test_playing_gain_unchanged_and_save_deferred(harness, tmp_path, busy):
    frame, service, calls, drain = harness
    item = add_tracks(frame, tmp_path).items[0]
    player = SimpleNamespace(set_gain_db=Mock(), _preloaded_path=None, _stream=0)
    frame._audio_engine._players['device'] = player
    if busy in ('playing', 'paused'):
        frame._playback.contexts[('list', item.id)] = SimpleNamespace(path=item.path, player=player)
    elif busy == 'preloaded':
        player._preloaded_path = item.path
    elif busy == 'prepared_controller':
        frame._playback.preloaded_paths = lambda: [item.path]
    elif busy == 'stream_without_context':
        player._stream = 1  # BASS może nadal wygaszać po usunięciu kontekstu.
    else:
        frame._playback.preview_context = SimpleNamespace(item_path=item.path, players=[player])
    service.poll()
    drain(lambda: item.replay_gain_db is not None)
    assert item.replay_gain_db == 1.0
    player.set_gain_db.assert_not_called()
    assert not extract_metadata(item.path).sara_loudness
    frame._playback.contexts.clear()
    frame._playback.preview_context = None
    frame._playback.preloaded_paths = lambda: []
    player._preloaded_path = None
    player._stream = 0
    service.poll()
    drain(lambda: bool(extract_metadata(item.path).sara_loudness))
    assert str(APEv2(item.path)['SARA_LOUDNESS']) == MARKER
    player.set_gain_db.assert_not_called()


def test_new_gain_is_used_only_on_next_real_controller_start(harness, tmp_path):
    from test_playback_controller import DummyAudioEngine, PlaybackController
    frame, service, calls, drain = harness
    model = add_tracks(frame, tmp_path)
    model.set_output_slots(['dev-1', 'dev-2'])
    item = model.items[0]
    item.replay_gain_db = -4.0
    audio = DummyAudioEngine()
    controller = PlaybackController(audio, frame._settings, lambda *a: None)
    frame._audio_engine = audio
    frame._playback = controller
    def start():
        return controller.start_item(model, item, start_seconds=0.0,
                                     on_finished=lambda *a: None, on_progress=lambda *a: None)
    try:
        first = start()
        assert first is not None
        assert first.player.gain == -4.0
        service.poll()
        drain(lambda: bool(item.sara_loudness))
        assert first.player.gain == -4.0
        assert item.replay_gain_db == 1.0
        controller.stop_playlist(model.id, fade_duration=0.0)
        drain(lambda: bool(extract_metadata(item.path).sara_loudness))
        second = start()
        assert second is not None
        assert second.player.gain == 1.0
    finally:
        controller.stop_playlist(model.id, fade_duration=0.0)
        if controller._preload_executor is not None:
            controller._preload_executor.shutdown()


def test_disabled_and_news_are_not_measured(harness, tmp_path):
    frame, service, calls, drain = harness
    add_tracks(frame, tmp_path, kind=PlaylistKind.NEWS)
    service.poll()
    drain(lambda: True)
    assert calls == []
    frame._settings.set_auto_loudness(False)
    add_tracks(frame, tmp_path)
    service.poll()
    drain(lambda: True)
    assert calls == []


def test_missing_analyzer_logs_once(harness, tmp_path, monkeypatch, caplog):
    frame, service, calls, drain = harness
    monkeypatch.setattr(loudness, 'find_bs1770gain', lambda: None)
    add_tracks(frame, tmp_path, 3)
    for _ in range(3):
        service.poll()
        drain(lambda: True)
    assert calls == []
    assert len([r for r in caplog.records if 'bs1770gain' in r.message]) == 1


def test_measurement_error_not_retried(harness, tmp_path, monkeypatch, caplog):
    frame, service, calls, drain = harness
    item = add_tracks(frame, tmp_path).items[0]
    def fail(*args, **kwargs):
        raise RuntimeError('pomiar niedostępny')
    monkeypatch.setattr(loudness.subprocess, 'run', fail)
    service.poll()
    drain(lambda: any('pomiar niedostępny' in r.message for r in caplog.records))
    count = len(caplog.records)
    for _ in range(3):
        service.poll()
        drain(lambda: True)
    assert len(caplog.records) == count
    assert item.replay_gain_db is None


def test_failed_write_keeps_model_without_persistent_marker(harness, tmp_path, monkeypatch, caplog):
    from sara.ui.services import auto_loudness
    frame, service, calls, drain = harness
    item = add_tracks(frame, tmp_path).items[0]
    writer = Mock(return_value=False)
    monkeypatch.setattr(auto_loudness, 'save_replay_gain_metadata', writer)
    service.poll()
    drain(lambda: item.replay_gain_db is not None)
    assert item.replay_gain_db == 1.0
    assert not extract_metadata(item.path).sara_loudness
    assert any(r.levelname == 'WARNING' and 'ReplayGain' in r.message for r in caplog.records)
    for _ in range(3):
        service.poll()
    assert writer.call_count == 1


def test_reload_retries_failed_write_without_another_measurement(harness, tmp_path, monkeypatch):
    from sara.ui.services import auto_loudness
    frame, service, calls, drain = harness
    model = add_tracks(frame, tmp_path)
    item = model.items[0]
    real_writer = auto_loudness.save_replay_gain_metadata
    writer = Mock(return_value=False)
    monkeypatch.setattr(auto_loudness, 'save_replay_gain_metadata', writer)
    service.poll()
    drain(lambda: bool(item.sara_loudness))
    assert writer.call_count == 1
    monkeypatch.setattr(auto_loudness, 'save_replay_gain_metadata', real_writer)
    model.items = item_loading.create_items_from_paths(frame, [item.path])
    service.poll()
    drain(lambda: bool(extract_metadata(item.path).sara_loudness))
    assert len(calls) == 1


def test_inflight_preload_blocks_tag_write(harness, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    frame, service, calls, drain = harness
    item = add_tracks(frame, tmp_path).items[0]
    player = SimpleNamespace(_preloaded_path=None, _stream=0, set_gain_db=Mock())
    frame._audio_engine._players['device'] = player
    entered, release = threading.Event(), threading.Event()
    executor = ThreadPoolExecutor(max_workers=1)
    frame._playback._preload_executor = executor
    def preload():
        entered.set()
        release.wait(2)
        player._preloaded_path = item.path
    executor.submit(preload)
    assert entered.wait(1)
    try:
        service.poll()
        drain(lambda: item.replay_gain_db is not None)
        assert not extract_metadata(item.path).sara_loudness
        release.set()
        executor.submit(lambda: None).result(1)
        for _ in range(3):
            service.poll()
        assert not extract_metadata(item.path).sara_loudness
        player._preloaded_path = None
        drain(lambda: bool(extract_metadata(item.path).sara_loudness))
    finally:
        release.set()
        executor.shutdown()


def test_new_preload_after_completed_barrier_still_blocks_write(harness, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    frame, service, calls, drain = harness
    item = add_tracks(frame, tmp_path).items[0]
    executor = ThreadPoolExecutor(max_workers=1)
    frame._playback._preload_executor = executor
    player = SimpleNamespace(_preloaded_path=None, _stream=0)
    frame._audio_engine._players['device'] = player
    frame._playback.contexts['live'] = SimpleNamespace(path=item.path, player=player)
    entered, release = threading.Event(), threading.Event()
    try:
        service.poll()
        drain(lambda: bool(item.sara_loudness))
        service.poll()  # Ostatnia bariera kończy się, zanim nadejdzie następny preload.
        executor.submit(lambda: None).result(1)
        frame._playback.contexts.clear()
        def preload():
            entered.set()
            release.wait(2)
            player._preloaded_path = item.path
        frame._playback._preload_executor.submit(preload)
        assert entered.wait(1)
        service.poll()
        assert not extract_metadata(item.path).sara_loudness
    finally:
        release.set()
        executor.shutdown()


def test_foreign_id3_gain_does_not_override_sara_ape(tmp_path, monkeypatch):
    from sara.core.media_metadata import extract as extract_module
    path = tmp_path / 'tags.mp3'
    path.write_bytes(b'fixture')
    save_replay_gain_metadata(path, 1.0, sara_loudness=MARKER)
    monkeypatch.setattr(extract_module, 'MutagenFile', lambda p: SimpleNamespace(
        tags={'REPLAYGAIN_TRACK_GAIN': '+9.00 dB'}, info=SimpleNamespace(length=20)))
    metadata = extract_metadata(path)
    assert metadata.replay_gain_db == 1.0
    assert metadata.sara_loudness == MARKER


def test_close_discards_pending_results(harness, tmp_path, monkeypatch):
    frame, service, calls, drain = harness
    items = add_tracks(frame, tmp_path, 3).items
    entered, release = threading.Event(), threading.Event()
    original = loudness.subprocess.run
    def wait(*args, **kwargs):
        entered.set()
        release.wait(2)
        return original(*args, **kwargs)
    monkeypatch.setattr(loudness.subprocess, 'run', wait)
    service.poll()
    assert entered.wait(1)
    start = time.monotonic()
    service.close()
    assert time.monotonic() - start < 0.2
    release.set()
    drain(lambda: bool(calls))
    assert len(calls) == 1
    assert all(i.replay_gain_db is None for i in items)


def test_default_setting_and_persistence(tmp_path):
    settings = SettingsManager(tmp_path / 'settings.yaml')
    assert settings.get_auto_loudness() is True
    settings.set_auto_loudness(False)
    settings.save()
    assert SettingsManager(settings.config_path).get_auto_loudness() is False
