"""Integracja z prawdziwą pętlą wx, bez sprzętowego backendu audio."""
# ruff: noqa: E402
# Importy wx zależnych modułów muszą następować po importorskip.
from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mutagen.apev2 import APEv2

wx = pytest.importorskip('wx')
if not wx.App.IsDisplayAvailable():
    pytest.skip('wx display required', allow_module_level=True)

from sara.core import loudness
from sara.core.app_state import AppState, PlaylistFactory
from sara.core.config import SettingsManager
from sara.core.i18n import set_language
from sara.core.media_metadata import extract_metadata
from sara.ui.controllers.frame import bootstrap
from sara.ui.main_frame import MainFrame
from sara.ui.dialogs.options.dialog import OptionsDialog
from sara.ui.dialogs.mix_point.dialog import MixPointEditorDialog
from sara.ui.dialogs.mix_point import loudness_ui
from test_auto_loudness import XML, MARKER


@pytest.fixture(scope='module')
def app():
    yield wx.GetApp() or wx.App()


def pump(predicate, timeout=4):
    # Prawdziwa MainLoop jak w działającej SARZE. Na Windows wx.Timer nie
    # dostarcza zdarzeń przez samo wx.Yield poza pętlą główną (pomiar
    # 25.10.2026: 0 tyknięć w 1 s przez Yield, 10 w MainLoop).
    app = wx.GetApp()
    state = {'ok': predicate()}
    if not state['ok']:
        deadline = time.monotonic() + timeout

        def check():
            if predicate():
                state['ok'] = True
                app.ExitMainLoop()
            elif time.monotonic() >= deadline:
                app.ExitMainLoop()
            else:
                wx.CallLater(10, check)

        wx.CallLater(10, check)
        app.MainLoop()
    assert state['ok'] or predicate(), 'Nie otrzymano wyniku w pętli wx'


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    settings = SettingsManager(tmp_path / 'settings.yaml')
    settings.set_remote_enabled(False)
    settings.set_language('pl')
    engine = SimpleNamespace(_players={}, stop_all=Mock(), get_devices=lambda: [])
    monkeypatch.setattr(bootstrap, 'AudioEngine', lambda: engine)
    monkeypatch.setattr(loudness, 'find_bs1770gain', lambda: Path('bs1770gain'))
    monkeypatch.setattr(loudness_ui, 'find_bs1770gain', lambda: Path('bs1770gain'))
    monkeypatch.setattr(loudness_ui, 'speak_text', lambda *a, **k: None)
    calls = []
    def run(cmd, **kwargs):
        calls.append((cmd, threading.get_ident()))
        return SimpleNamespace(returncode=0, stdout=XML, stderr='')
    monkeypatch.setattr(loudness.subprocess, 'run', run)
    state = AppState()
    factory = PlaylistFactory()
    path = tmp_path / 'startup.mp3'
    path.write_bytes(b'fixture')
    item = factory.create_item(path, 'Startowy', 20)
    model = factory.create_playlist('Muzyka', items=[item])
    state.add_playlist(model)
    frame = MainFrame(state=state, settings=settings)
    frame._announce_event = Mock()
    frame.Show()
    yield frame, calls
    frame.Close()
    pump(lambda: frame._auto_loudness._stop.is_set())
    wx.Yield()
    set_language('en')


def test_startup_and_all_addition_routes_use_live_timer(window, tmp_path):
    frame, calls = window
    model = next(iter(frame._state.playlists.values()))
    panel = frame._playlists[model.id]
    pump(lambda: bool(model.items[0].sara_loudness))
    frame._announce_event.reset_mock()
    # Import M3U, pliki/folder i schowek idą różnymi drogami do modelu.
    paths = []
    for i in range(3):
        path = tmp_path / f'added-{i}.mp3'
        path.write_bytes(b'fixture')
        paths.append(path)
    frame._finalize_add_tracks(panel, frame._create_items_from_paths([paths[0]]))
    frame._finalize_import_playlist(panel, frame._create_items_from_m3u_entries([{'path': paths[1]}]), 'lista.m3u')
    frame._finalize_clipboard_paste(panel, model, frame._create_items_from_paths([paths[2]]), len(model.items), None, skipped_files=0)
    frame._announce_event.reset_mock()
    pump(lambda: len(model.items) == 4 and all(i.sara_loudness for i in model.items))
    assert len(calls) == 4
    assert all(tid != threading.get_ident() for _, tid in calls)
    assert all(extract_metadata(path).sara_loudness == MARKER for path in paths)
    frame._announce_event.assert_not_called()


def test_options_polish_label_and_save(window):
    frame, calls = window
    dialog = OptionsDialog(frame, settings=frame._settings, audio_engine=frame._audio_engine)
    try:
        checkbox = dialog._auto_loudness_checkbox
        expected = 'Automatycznie wyrównuj głośność nowych utworów do EBU R128 (-23 LUFS)'
        assert checkbox.GetValue() is True
        assert checkbox.GetLabel() == expected
        assert checkbox.GetName() == expected
        checkbox.SetValue(False)
        wx.CallAfter(dialog._on_accept, None)
        assert dialog.ShowModal() == wx.ID_OK
        assert frame._settings.get_auto_loudness() is False
    finally:
        dialog.Destroy()


@pytest.mark.parametrize('standard_index,expected_gain,label', [(0, 1.0, 'EBU R128'), (1, 1.0, 'ATSC A/85')])
def test_normalize_button_uses_shared_result_and_marker(window, standard_index, expected_gain, label):
    frame, calls = window
    model = next(iter(frame._state.playlists.values()))
    item = model.items[0]
    pump(lambda: bool(item.sara_loudness))
    frame._settings.set_auto_loudness(False)
    dialog = MixPointEditorDialog(
        frame, title='Punkty miksu', duration_seconds=20, cue_in_seconds=None,
        intro_seconds=None, outro_seconds=None, segue_seconds=None,
        segue_fade_seconds=None, overlap_seconds=None, on_preview=lambda *a: True,
        on_stop_preview=lambda: None, track_path=item.path,
        initial_replay_gain=None,
        on_replay_gain_update=lambda gain, marker: frame._apply_replay_gain(item, gain, marker),
    )
    try:
        dialog._standard_radio.SetSelection(standard_index)
        dialog._handle_normalize(None)
        pump(lambda: not dialog._normalizing)
        assert item.replay_gain_db == expected_gain
        assert item.sara_loudness.startswith(label)
        assert str(APEv2(item.path)['SARA_LOUDNESS']) == item.sara_loudness
        assert len(calls) == 2
        assert all(tid != threading.get_ident() for _, tid in calls)
    finally:
        dialog.Destroy()


def test_destroy_stops_timer_and_worker(window):
    frame, calls = window
    frame._on_close(SimpleNamespace(Skip=lambda: None))
    assert not frame._auto_loudness_timer.IsRunning()
    assert frame._auto_loudness._stop.is_set()
