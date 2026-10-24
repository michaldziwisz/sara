from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import socket
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
from sara.core.i18n import gettext as _, set_language
from sara.core.playlist import PlaylistItemStatus as Status
from sara.remote.commands import CommandSession
from sara.remote.server import MainThreadDispatcher, RemoteServer
from sara.ui.controllers.playback.navigation import on_global_play_next, manual_fade_duration
from sara.ui.controllers.playlists.hotkeys import handle_playlist_hotkey
from sara.ui.controllers.playlists.focus import on_toggle_selection
from sara.ui.dialogs.options.dialog import OptionsDialog
from sara.ui.panels.playlist.panel import PlaylistPanel
from sara.ui.services.remote_control import configure_remote_control, stop_remote_control
from test_remote_commands import Frame
from test_remote_server import exchange


@pytest.fixture(scope="module")
def app():
    instance = wx.GetApp() or wx.App()
    yield instance


@pytest.fixture
def gui_frame(app):
    frame = Frame()
    host = wx.Frame(None)
    panel = PlaylistPanel(host, frame.panel.model)
    frame.panel = panel
    frame._playlists["music"] = panel
    frame._get_playlist_model = lambda pid: frame._playlists[pid].model
    frame._on_toggle_selection = MethodType(on_toggle_selection, frame)
    frame._on_playlist_hotkey = MethodType(handle_playlist_hotkey, frame)
    frame._on_global_play_next = MethodType(on_global_play_next, frame)
    frame._active_news_panel = lambda: (None, None)
    frame._start_next_from_playlist = Mock(return_value=True)
    frame._play_next_alternate = Mock(return_value=True)
    frame._auto_mix_play_next = Mock(return_value=True)
    yield frame, host
    host.Destroy()
    wx.Yield()


def test_remote_select_and_queue_match_real_panel_without_window_focus(gui_frame):
    frame, host = gui_frame
    other = wx.Frame(None)
    button = wx.Button(other, label="Inne okno")
    other.Show()
    button.SetFocus()
    wx.Yield()
    focus_before = wx.Window.FindFocus()
    assert focus_before is button
    session = CommandSession(frame)
    try:
        assert session.execute_line("SelectIndex=1") == ["1"]
        assert frame.panel.get_selected_indices() == [1]
        assert frame.panel.get_focused_index() == 1
        assert session.execute_line("CheckToggle") == ["1"]
        assert frame.panel.model.items[1].is_selected
        assert "[" in frame.panel._list_ctrl.GetItemText(1)
        assert wx.Window.FindFocus() is button
        frame._announce_event.assert_not_called()
        assert session.execute_line("CheckToggle") == ["0"]
        assert frame._announce_event.call_count == 1
        frame._auto_mix_enabled = True
        assert session.execute_line("CheckToggle") == ["0"]
        assert not frame.panel.model.items[1].is_selected
        assert wx.Window.FindFocus() is button
    finally:
        other.Destroy()


@pytest.mark.parametrize("command", ["Play", "Skip"])
@pytest.mark.parametrize("mode", ["manual", "auto", "alternate"])
def test_remote_uses_real_navigation_controller(gui_frame, command, mode):
    frame, host = gui_frame
    frame._alternate_play_next = mode == "alternate"
    frame._auto_mix_enabled = mode == "auto"
    CommandSession(frame).execute_line(command)
    expected = {"manual": frame._start_next_from_playlist, "auto": frame._auto_mix_play_next,
                "alternate": frame._start_next_from_playlist}[mode]
    assert expected.call_count == 1


def test_play_without_playlist_uses_existing_announcement(gui_frame):
    frame, host = gui_frame
    frame._playlists.clear()
    frame.panel = None
    CommandSession(frame).execute_line("Play")
    frame._announce_event.assert_called_once_with("playlist", _("No playlists available"))
    frame._start_next_from_playlist.assert_not_called()


@pytest.mark.parametrize("command,mark_played,fade", [("Stop", True, 2.5), ("Instant Stop", False, 0.0)])
def test_stop_uses_existing_hotkey_and_manual_fade(gui_frame, command, mark_played, fade):
    frame, host = gui_frame
    item = frame.panel.model.items[0]
    item.status = Status.PLAYING
    frame._playback.contexts[("music", "a")] = SimpleNamespace(player=Mock())
    frame._manual_fade_duration = MethodType(manual_fade_duration, frame)
    frame._fade_duration = 2.5
    frame._mix_plans = {}
    frame._measure_effective_duration = lambda playlist, item: None
    frame._resolve_mix_timing = lambda item, **kwargs: (None, 0.0, 5.0, 120.0)
    frame._stop_playlist_playback = Mock()
    frame._set_auto_mix_enabled = Mock()
    CommandSession(frame).execute_line(command)
    frame._stop_playlist_playback.assert_called_once_with("music", mark_played=mark_played, fade_duration=fade)
    frame._set_auto_mix_enabled.assert_called_once_with(False, reason=_("Auto mix disabled (manual stop)"))
    assert frame._announce_event.call_count == 1


def test_pause_is_existing_f2_and_repeated_pause_has_no_new_announcement(gui_frame):
    frame, host = gui_frame
    item = frame.panel.model.items[0]
    item.status = Status.PLAYING
    item.current_position = 12
    player = Mock()
    frame._playback.contexts[("music", "a")] = SimpleNamespace(player=player)
    session = CommandSession(frame)
    assert session.execute_line("Pause")[0][4] == "1"
    assert session.execute_line("Pause")[0][4] == "1"
    player.pause.assert_called_once_with()
    assert item.status is Status.PAUSED
    assert item.current_position == 12
    assert frame._announce_event.call_count == 1


def test_real_wx_callafter_delivers_socket_commands_on_gui_thread(app):
    frame = Frame()
    thread_ids = []
    frame._start_next_from_playlist = lambda panel: thread_ids.append(threading.get_ident()) or True
    dispatcher = MainThreadDispatcher(wx.CallAfter)
    server = RemoteServer(dispatcher, lambda: CommandSession(frame), port=0)
    server.start()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            request = pool.submit(exchange, server.address, b"Play\n", 1)
            deadline = time.monotonic() + 3
            while not request.done() and time.monotonic() < deadline:
                wx.Yield()
                time.sleep(0.005)
            assert request.result(timeout=1) == [b"0000001\r\n"]
        assert thread_ids == [threading.main_thread().ident]
    finally:
        server.stop()


def test_options_labels_and_accept_persist_remote_settings(app, tmp_path):
    settings = SettingsManager(tmp_path / "settings.yaml")
    set_language("pl")
    dialog = OptionsDialog(None, settings=settings, audio_engine=SimpleNamespace(get_devices=lambda: []))
    try:
        assert dialog._remote_enabled_checkbox.GetLabel() == "Włącz lokalne sterowanie TCP (127.0.0.1)"
        assert dialog._remote_port_ctrl.GetName() == "Port sterowania TCP"
        assert dialog._remote_port_ctrl.GetMin() == 1
        assert dialog._remote_port_ctrl.GetMax() == 65535
        dialog._remote_enabled_checkbox.SetValue(False)
        dialog._remote_port_ctrl.SetValue(52345)
        dialog.EndModal = Mock()
        dialog._on_accept(None)
        assert not settings.get_remote_enabled()
        assert settings.get_remote_port() == 52345
    finally:
        dialog.Destroy()
        set_language("en")


def test_main_frame_starts_and_closes_server(app, tmp_path, monkeypatch):
    from sara.ui.controllers.frame import bootstrap
    from sara.ui.main_frame import MainFrame

    engine = Mock()
    engine.get_devices.return_value = []
    monkeypatch.setattr(bootstrap, "AudioEngine", lambda: engine)
    settings = SettingsManager(tmp_path / "settings.yaml")
    settings.set_remote_port(unused_port())
    frame = MainFrame(None, settings=settings)
    server = frame._remote_server
    try:
        assert server.address == ("127.0.0.1", settings.get_remote_port())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(exchange, server.address, b"Helo,Play,LastIndex\n", 3)
            deadline = time.monotonic() + 3
            while not future.done() and time.monotonic() < deadline:
                wx.Yield()
                time.sleep(0.005)
            assert future.result(timeout=1) == [b"SARA v0.0.37\r\n", b"0000001\r\n", b"-1\r\n"]
        frame.Close()
        wx.Yield()
        with pytest.raises(OSError):
            socket.create_connection(server.address, timeout=0.2)
    finally:
        server.stop()
        if frame:
            frame.Destroy()


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_service_enable_disable_reconfigure_and_conflict(app, tmp_path):
    frame = Frame()
    frame._settings = SettingsManager(tmp_path / "settings.yaml")
    frame._settings.set_remote_port(unused_port())
    configure_remote_control(frame)
    first = frame._remote_server
    assert first is not None
    configure_remote_control(frame)
    assert frame._remote_server is first
    frame._settings.set_remote_port(unused_port())
    configure_remote_control(frame)
    second = frame._remote_server
    assert second is not first
    with pytest.raises(OSError):
        socket.create_connection(first.address, timeout=0.2)
    frame._settings.set_remote_enabled(False)
    configure_remote_control(frame)
    assert frame._remote_server is None
    with pytest.raises(OSError):
        socket.create_connection(second.address, timeout=0.2)
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        frame._settings.set_remote_port(blocker.getsockname()[1])
        frame._settings.set_remote_enabled(True)
        configure_remote_control(frame)
        assert frame._remote_server is None
        assert frame._announce_event.call_count == 1
    stop_remote_control(frame)
