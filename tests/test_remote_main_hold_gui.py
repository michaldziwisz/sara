from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import socket
import statistics
import threading
import time
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.gui
if os.environ.get("WX_RUN_GUI_TESTS") != "1":
    pytest.skip("wx GUI tests are opt-in (set WX_RUN_GUI_TESTS=1)", allow_module_level=True)
wx = pytest.importorskip("wx")
if not wx.App.IsDisplayAvailable():
    pytest.skip("wx display required", allow_module_level=True)

from sara.core.config import SettingsManager
from sara.core.i18n import set_language
from sara.remote.commands import CommandSession
from sara.ui.controllers.playlists.focus import on_toggle_selection
from sara.ui.panels.news.toolbar_navigation import activate_toolbar_control
from sara.ui.panels.playlist.panel import PlaylistPanel
from sara.ui.dialogs.options.dialog import OptionsDialog
from sara.ui.services.remote_control import configure_remote_control, stop_remote_control
from test_remote_hold import hold_frame
from test_remote_main_playlist import main_frame, playing


@pytest.fixture(scope="module")
def app():
    yield wx.GetApp() or wx.App()


def pump_until(done, timeout=2):
    deadline = time.monotonic() + timeout
    while not done() and time.monotonic() < deadline:
        wx.Yield()
        time.sleep(0.001)
    assert done(), "Nie nadeszło oczekiwane zdarzenie wx"


@pytest.fixture
def service(app, tmp_path):
    frame, item, ctx = hold_frame()
    frame._settings = SettingsManager(tmp_path / "settings.yaml")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    frame._settings.set_remote_port(port)
    configure_remote_control(frame)
    yield frame, item, ctx
    stop_remote_control(frame)
    wx.Yield()


def test_news_save_focus_remote_play_never_presses_save(app):
    frame = main_frame()
    host = wx.Frame(None)
    news = wx.Panel(host)
    save = wx.Button(news, label="Zapisz")
    clicked = Mock()
    save.Bind(wx.EVT_BUTTON, clicked)
    news._mode_button = news._insert_button = news._load_button = None
    news._save_button, news._line_length_apply = save, None
    news.activate_toolbar_control = MethodType(activate_toolbar_control, news)
    frame._active_news_panel = lambda: (news, wx.Window.FindFocus())
    host.Show()
    save.SetFocus()
    wx.Yield()
    assert wx.Window.FindFocus() is save
    try:
        CommandSession(frame).execute_line("Play")
        clicked.assert_not_called()
        frame._start_next_from_playlist.assert_called_once_with(frame.panel)
        wx.Yield()
        assert wx.Window.FindFocus() is save
        assert frame._layout.state.current_id == "news"
        # Kontrola dodatnia: Spacja na tym samym przycisku nadal go naciska.
        frame._on_global_play_next(None)
        clicked.assert_called_once()
    finally:
        host.Destroy()
        wx.Yield()


def test_real_panel_selection_events_do_not_activate_main(app):
    frame = main_frame()
    host = wx.Frame(None)
    other = wx.Frame(None)
    save = wx.Button(other, label="Zapisz wiadomości")
    panel = PlaylistPanel(host, frame.panel.model, on_focus=frame._layout.set_current)
    frame.panel = frame._playlists["music"] = panel
    frame._get_playlist_model = lambda pid: frame._playlists[pid].model
    frame._on_toggle_selection = MethodType(on_toggle_selection, frame)
    host.Show()
    other.Show()
    save.SetFocus()
    wx.Yield()
    panel.set_selection([0])
    frame._layout.state.current_id = "news"
    try:
        session = CommandSession(frame)
        assert session.execute_line("SelectIndex=+") == ["1"]
        assert session.execute_line("CheckToggle") == ["1"]
        item, ctx = playing(frame)
        session.execute_line("Pause")
        wx.Yield()
        assert frame._layout.state.current_id == "news"
        assert wx.Window.FindFocus() is save
        assert panel.get_focused_index() == 1
        assert session.execute_line("Hold=1") == ["1,trzyma"]
        assert session.execute_line("Hold=0") == ["0,trzyma"]
        wx.Yield()
        assert panel.get_focused_index() == 1
        assert frame._layout.state.current_id == "news"
        assert wx.Window.FindFocus() is save
        # Ochrona nie może wyłączyć normalnego wyboru myszą/klawiaturą.
        panel.select_index(0)
        wx.Yield()
        assert frame._layout.state.current_id == "music"
    finally:
        other.Destroy()
        host.Destroy()
        wx.Yield()


def test_timer_protects_keyboard_started_track_within_150ms(service):
    frame, item, ctx = service
    assert CommandSession(frame).execute_line("Hold=1") == ["1,trzyma"]
    # Rzeczywisty handler Spacji; tylko sam backend startu pozostaje atrapą.
    frame._layout.state.current_id = "music"
    frame._auto_mix_play_next = Mock(side_effect=lambda panel: playing(frame, index=1) and True)
    started = time.perf_counter()
    frame._on_global_play_next(None)
    incoming = frame.panel.model.items[1]
    frame._layout.state.current_id = "news"
    pump_until(lambda: incoming.break_after, timeout=0.15)
    elapsed = (time.perf_counter() - started) * 1000
    assert elapsed <= 150
    assert frame.triggers[("music", "b")] == (None, None)
    print(f"Hold timer: {elapsed:.3f} ms")


@pytest.mark.parametrize("shutdown", ["stop", "disable", "close"])
def test_service_shutdown_releases_without_start(service, shutdown):
    frame, item, ctx = service
    session = CommandSession(frame)
    session.execute_line("Hold=1")
    if shutdown == "disable":
        frame._settings.set_remote_enabled(False)
        configure_remote_control(frame)
    elif shutdown == "close":
        from sara.ui.main_frame import MainFrame
        frame._jingles.stop_all = Mock()
        event = Mock()
        MainFrame._on_close(frame, event)
        event.Skip.assert_called_once()
    else:
        stop_remote_control(frame)
    assert not item.break_after
    assert session.execute_line("Hold") == ["0,trzyma"]
    assert frame.triggers[("music", "a")][0] == 118.0
    incoming, new = playing(frame, index=1)
    deadline = time.monotonic() + 0.2
    pump_until(lambda: time.monotonic() >= deadline)
    assert not incoming.break_after
    frame._start_next_from_playlist.assert_not_called()
    frame._auto_mix_play_next.assert_not_called()


def test_hold_socket_latency_and_main_thread(service):
    frame, item, ctx = service
    threads = []
    original = frame._playback.update_mix_trigger.side_effect
    def update(*args, **kwargs):
        threads.append(threading.current_thread())
        return original(*args, **kwargs)
    frame._playback.update_mix_trigger.side_effect = update
    def client():
        timings = []
        with socket.create_connection(frame._remote_server.address, timeout=2) as sock:
            with sock.makefile("rb") as reader:
                for _ in range(20):
                    start = time.perf_counter()
                    sock.sendall(b"Hold=1\n")
                    reply = reader.readline()
                    timings.append((time.perf_counter() - start) * 1000)
                    assert reply == b"1,trzyma\r\n"
                    sock.sendall(b"Hold=0\n")
                    assert reader.readline() == b"0,trzyma\r\n"
        return timings
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client)
        pump_until(future.done, timeout=5)
        timings = future.result()
    print(f"Hold=1 TCP n={len(timings)} min={min(timings):.3f} median={statistics.median(timings):.3f} max={max(timings):.3f} ms")
    assert max(timings) < 30
    assert threads and all(t is threading.main_thread() for t in threads)


def test_options_main_playlist_names_and_roundtrip(app, tmp_path):
    settings = SettingsManager(tmp_path / "settings.yaml")
    frame = main_frame()
    host = wx.Frame(None)
    host._playlists, host._layout = frame._playlists, frame._layout
    set_language("pl")
    dialog = OptionsDialog(host, settings=settings, audio_engine=SimpleNamespace(get_devices=lambda: []))
    try:
        choice = dialog._remote_main_playlist_choice
        assert choice.GetName() == "Główna playlista muzyczna"
        assert choice.GetStrings() == ["Pierwsza muzyczna", "Muzyka", "Druga"]
        assert choice.GetSelection() == 0
        choice.SetSelection(2)
        dialog.EndModal = Mock()
        dialog._on_accept(None)
        settings.save()
        assert SettingsManager(settings.config_path).get_remote_main_playlist() == "second"
    finally:
        dialog.Destroy()
        host.Destroy()
        set_language("en")
        wx.Yield()
