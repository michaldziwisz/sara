from __future__ import annotations

import copy
import hashlib
import queue
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from types import MethodType
from unittest.mock import Mock

import pytest

from sara.core.mix_planner import clear_mix_plan, register_mix_plan, resolve_mix_timing
from sara.remote.commands import CommandSession
from sara.remote.server import MainThreadDispatcher, RemoteServer
from sara.ui.controllers.mix.points import propagate_mix_points_for_path
from sara.ui.controllers.mix.preview import preview_mix_with_next
from sara.ui.playback.preview import start_preview, stop_preview
from test_remote_hold import hold_frame
from test_remote_main_playlist import playing
from test_remote_server import exchange, pump_until


@pytest.fixture
def mix_frame(tmp_path):
    frame, item, ctx = hold_frame()
    path = tmp_path / "mix.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x00\x00" * 8000)
    item.path = path
    frame.panel.focused = 0
    frame._fade_duration = 2.0
    frame._mix_trigger_points = {}
    frame._register_mix_plan = lambda pid, iid, **kw: register_mix_plan(
        frame._mix_plans, frame._mix_trigger_points, pid, iid, **kw)
    frame._clear_mix_plan = lambda pid, iid: clear_mix_plan(
        frame._mix_plans, frame._mix_trigger_points, pid, iid)
    frame._resolve_mix_timing = lambda item, overrides=None, **kw: resolve_mix_timing(
        item, frame._fade_duration, overrides, **kw)
    frame._apply_mix_trigger_to_playback(playlist_id="music", item=item, panel=frame.panel)
    frame._propagate_mix_points_for_path = MethodType(propagate_mix_points_for_path, frame)
    frame._apply_loop_setting_to_playback = Mock()
    frame._stop_preview = Mock()
    frame._playback.start_preview = Mock(return_value=True)
    frame._preview_mix_with_next = Mock(return_value=True)
    ctx.player.get_position_seconds.return_value = 50.0
    frame._playlists["second"].model.items[0].path = path
    yield frame, item, ctx
    owner = getattr(frame, "_remote_mix_owner", None)
    if owner is not None:
        owner.close()


def request(session, command):
    responses = session.execute_line(command)
    assert len(responses) == 1
    return responses[0]


def open_mix(frame):
    session = CommandSession(frame)
    assert request(session, "mIxOpEn") == "OK|0|1|125000|Żółw|Tytuł"
    return session


def set_point(session, key, seconds):
    assert not request(session, "MixPoint=" + key).startswith("ERR")
    assert not request(session, f"MixPos=@{seconds}").startswith("ERR")
    assert not request(session, "MixSet").startswith("ERR")


def digest(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def test_open_main_cursor_ownership_and_no_session(mix_frame):
    frame, item, _ = mix_frame
    session = open_mix(frame)
    assert frame._layout.state.current_id == "news"
    assert request(session, "MixInfo") == "5000|cue|5000|0|brak"
    assert request(session, "MixOpen") == "ERR session"
    other = CommandSession(frame)
    assert request(other, "MixOpen") == "ERR session"
    assert request(other, "MixSet") == "ERR nosession"
    assert request(session, "MixCancel") == "OK"
    for command in ("MixInfo", "MixPos=+1", "MixPoint=next", "MixSet", "MixNudge=+0.1",
                    "MixClear", "MixPlay", "MixPlayPoint", "MixPlayMix", "MixStop", "MixUndo",
                    "MixSave", "MixCancel"):
        assert request(session, command) == "ERR nosession"


def test_busy_empty_and_sanitized_title(mix_frame):
    frame, item, _ = mix_frame
    session = CommandSession(frame)
    frame._mix_points_dialog_open = True
    assert request(session, "MixOpen") == "ERR busy"
    frame._mix_points_dialog_open = False
    frame.panel.focused = -1
    assert request(session, "MixOpen") == "ERR empty"
    frame.panel.focused = 0
    item.title = "A|B\r\nC\x00"
    assert request(session, "MixOpen") == "OK|0|1|125000|Żółw|A B  C "
    request(session, "MixCancel")
    frame._playlists.clear()
    assert request(session, "MixOpen") == "ERR empty"


def test_navigation_clamp_set_clear_and_undo(mix_frame):
    frame, _, _ = mix_frame
    session = open_mix(frame)
    assert request(session, "MixPoint=prev") == "5000|loop_end|-|0|brak"
    assert request(session, "MixPoint=next") == "5000|cue|5000|0|brak"
    assert request(session, "MixPos=-99") == "0|cue|5000|0|brak"
    assert request(session, "MixPos=+999") == "125000|cue|5000|0|brak"
    set_point(session, "intro", 10)
    set_point(session, "outro", 100)
    assert request(session, "MixClear") == "100000|outro|-|1|brak"
    assert request(session, "MixUndo").split("|")[1:3] == ["outro", "100000"]
    request(session, "MixUndo")
    assert request(session, "MixInfo").split("|")[2] == "-"
    request(session, "MixUndo")
    assert request(session, "MixInfo").split("|")[3] == "0"
    assert request(session, "MixUndo") == request(session, "MixInfo")


@pytest.mark.parametrize("command", ["MixPos=nan", "MixPos=@inf", "MixPos=1e3", "MixPos=1",
    "MixNudge=@1", "MixNudge=+inf", "MixPoint=bad", "MixPos", "MixSet=1", "MixOpen=1"])
def test_bad_arguments_do_not_edit(mix_frame, command):
    frame, _, _ = mix_frame
    session = open_mix(frame)
    before = request(session, "MixInfo")
    assert request(session, command) == "ERR syntax"
    assert request(session, "MixInfo") == before


def test_save_reschedules_playing_track_and_reports_actual_plan(mix_frame):
    frame, item, ctx = mix_frame
    session = open_mix(frame)
    set_point(session, "segue", 55)
    assert request(session, "MixSave") == "OK|przejscie_za=5000"
    assert item.segue_seconds == 50  # W modelu od cue, na stole bezwzględnie.
    assert frame._mix_plans[("music", "a")].mix_at == 55
    assert frame.triggers[("music", "a")][0] == 55
    assert request(session, "MixInfo") == "ERR nosession"
    session = open_mix(frame)
    set_point(session, "segue", 45)
    assert request(session, "MixSave") == "OK|przejscie_teraz"
    assert frame.triggers[("music", "a")][0] == 45
    ctx.player.stop.assert_not_called()


def test_save_with_hold_keeps_hold_and_reports_no_transition(mix_frame):
    frame, item, _ = mix_frame
    session = open_mix(frame)
    assert request(session, "Hold=1") == "1,trzyma"
    set_point(session, "segue", 55)
    assert request(session, "MixSave") == "OK|brak_przejscia"
    assert item.break_after
    assert ("music", "a") not in frame._mix_plans
    assert request(session, "Hold") == "1,trzyma"


def test_save_without_plan_or_playback(mix_frame):
    frame, item, _ = mix_frame
    session = open_mix(frame)
    request(session, "MixPoint=segue")
    request(session, "MixClear")
    frame._fade_duration = 0
    assert request(session, "MixSave") == "OK|brak_przejscia"
    session = open_mix(frame)
    frame._playback.contexts.clear()
    assert request(session, "MixSave") == "OK|nie_gra"


def test_invalid_order_keeps_file_model_and_session(mix_frame):
    frame, item, _ = mix_frame
    before, before_md5 = copy.deepcopy(item), digest(item.path)
    session = open_mix(frame)
    set_point(session, "intro", 100)
    set_point(session, "outro", 10)
    assert request(session, "MixSave") == "ERR invalid|kolejnosc"
    assert item == before
    assert digest(item.path) == before_md5
    assert not request(session, "MixInfo").startswith("ERR")


def test_cancel_does_not_write_and_stops_preview(mix_frame):
    frame, item, _ = mix_frame
    before, before_md5 = copy.deepcopy(item), digest(item.path)
    session = open_mix(frame)
    set_point(session, "cue", 3)
    set_point(session, "intro", 20)
    request(session, "MixPlay")
    assert request(session, "MixCancel") == "OK"
    assert digest(item.path) == before_md5
    assert item == before
    frame._stop_preview.assert_called()


def test_nudge_overlap_and_loop_semantics(mix_frame):
    frame, _, _ = mix_frame
    session = open_mix(frame)
    set_point(session, "segue", 110)
    set_point(session, "overlap", 0)
    assert request(session, "MixInfo").split("|")[2] == "15000"
    request(session, "MixNudge=+0.1")
    assert request(session, "MixInfo").split("|")[:3] == ["110100", "overlap", "14900"]
    set_point(session, "loop_end", 30)
    request(session, "MixPoint=loop_start")
    assert request(session, "MixInfo").split("|")[2] == "0"
    set_point(session, "loop_start", 40)
    request(session, "MixPoint=loop_end")
    assert request(session, "MixInfo").split("|")[2] == "40010"
    request(session, "MixPoint=loop_start")
    request(session, "MixClear")
    request(session, "MixPoint=loop_end")
    assert request(session, "MixInfo").split("|")[2] == "-"


def test_preview_calls_existing_paths_without_touching_air(mix_frame):
    frame, item, ctx = mix_frame
    contexts = frame._playback.contexts.copy()
    session = open_mix(frame)
    assert request(session, "MixPlay").endswith("|pozycja")
    frame._playback.start_preview.assert_called_with(item, 5.0, loop_range=None)
    request(session, "MixPos=@20")
    frame._playback.start_preview.assert_called_with(item, 20.0, loop_range=None)
    assert request(session, "MixPlay").endswith("|brak")
    set_point(session, "intro", 10)
    assert request(session, "MixPlayPoint").endswith("|punkt")
    frame._playback.start_preview.assert_called_with(item, 10.0, loop_range=None)
    request(session, "MixNudge=+0.1")
    frame._playback.start_preview.assert_called_with(item, 10.1, loop_range=None)
    assert request(session, "MixPlayMix").endswith("|przejscie")
    frame._preview_mix_with_next.assert_called()
    assert request(session, "MixStop").endswith("|brak")
    assert frame._playback.contexts == contexts
    ctx.player.stop.assert_not_called()


def test_real_pfl_path_and_missing_device(mix_frame):
    from types import SimpleNamespace
    frame, item, ctx = mix_frame
    playback = frame._playback
    playback._preview_context = None
    playback._pfl_device_id = None
    playback._settings = SimpleNamespace(get_pfl_device=lambda: None)
    playback._announce = frame._announce_event
    playback.start_preview = MethodType(start_preview, playback)
    frame._stop_preview = lambda: stop_preview(playback)
    session = open_mix(frame)
    assert request(session, "MixPlay") == "ERR pfl"
    assert "Configure a PFL device in Options" in str(frame._announce_event.call_args)
    pfl = Mock()
    pfl.play.return_value = None
    playback._pfl_device_id = "pfl-device"
    playback.get_busy_device_ids = lambda: set()
    playback._audio_engine = Mock()
    playback._audio_engine.get_devices.return_value = [SimpleNamespace(id="pfl-device")]
    playback._audio_engine.create_player_instance.return_value = pfl
    assert request(session, "MixPlay").endswith("|pozycja")
    assert playback._preview_context.device_id == "pfl-device"
    assert playback._preview_context.players == [pfl]
    assert ctx in playback.contexts.values()
    ctx.player.stop.assert_not_called()
    request(session, "MixStop")
    assert playback._preview_context is None


def test_socket_disconnect_cancels_in_gui_even_after_dispatch_timeout(mix_frame):
    frame, item, _ = mix_frame
    before, before_md5 = copy.deepcopy(item), digest(item.path)
    callbacks = queue.Queue()
    dispatcher = MainThreadDispatcher(callbacks.put, timeout=0.05)
    server = RemoteServer(dispatcher, lambda: CommandSession(frame), port=0)
    server.start()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            job = pool.submit(exchange, server.address,
                b"MixOpen\nMixPos=@3\nMixSet\nMixPlay\n", 4)
            transcript = pump_until([job], callbacks)[0]
        print("TCP:", transcript)
        # Sprzątanie musi czekać na GUI, a nie przepadać jak zwykłe polecenie.
        time.sleep(0.1)
        deadline = time.monotonic() + 2
        while getattr(frame, "_remote_mix_owner", None) is not None:
            assert time.monotonic() < deadline
            callbacks.get(timeout=1)()
        assert transcript[0].startswith(b"OK|0|1|")
        assert item == before and digest(item.path) == before_md5
        frame._stop_preview.assert_called()
    finally:
        server.stop()


def test_start_on_air_does_not_end_editing(mix_frame):
    frame, item, _ = mix_frame
    frame._playback.contexts.clear()
    session = CommandSession(frame)
    assert request(session, "MixOpen").startswith("OK|0|0|")
    playing(frame)
    assert request(session, "MixInfo") == "5000|cue|5000|0|brak"


def test_socket_save_transcript_runs_on_gui(mix_frame):
    frame, item, _ = mix_frame
    callbacks = queue.Queue()
    server = RemoteServer(MainThreadDispatcher(callbacks.put), lambda: CommandSession(frame), port=0)
    server.start()
    calls = []
    propagate = frame._propagate_mix_points_for_path
    def record(**kwargs):
        calls.append(threading.current_thread())
        return propagate(**kwargs)
    frame._propagate_mix_points_for_path = record
    commands = ["MixOpen", "MixPoint=segue", "MixPos=@55", "MixSet", "MixSave", "MixInfo"]
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            job = pool.submit(exchange, server.address, ("\n".join(commands) + "\n").encode(), len(commands))
            responses = pump_until([job], callbacks)[0]
        for command, response in zip(commands, responses):
            print(command, "->", response.decode().strip())
        assert responses[-2:] == [b"OK|przejscie_za=5000\r\n", b"ERR nosession\r\n"]
        assert calls == [threading.main_thread()]
        assert item.segue_seconds == 50
    finally:
        server.stop()


def test_invalid_loop_keeps_file_and_model(mix_frame):
    frame, item, _ = mix_frame
    item.loop_start_seconds, item.loop_end_seconds = 20, 10
    before, before_md5 = copy.deepcopy(item), digest(item.path)
    session = open_mix(frame)
    assert request(session, "MixSave") == "ERR invalid|petla"
    assert item == before and digest(item.path) == before_md5
    assert request(session, "MixInfo").endswith("|brak")


def test_other_disconnect_does_not_cancel_owner(mix_frame):
    frame, _, _ = mix_frame
    session = open_mix(frame)
    CommandSession(frame).close()
    assert request(session, "MixInfo").startswith("5000|cue|")
    session.close()
    assert request(session, "MixInfo") == "ERR nosession"


def test_segue_preview_uses_window_timer_fallback_and_existing_mix_path(mix_frame, monkeypatch):
    frame, item, _ = mix_frame
    frame._index_of_item = lambda model, iid: model.index_of(iid)
    frame._measure_effective_duration = lambda model, item: item.effective_duration_seconds
    frame._preview_mix_with_next = MethodType(preview_mix_with_next, frame)
    frame._playback.start_mix_preview = Mock(return_value=True)
    session = open_mix(frame)
    set_point(session, "segue", 110)
    request(session, "MixPoint=segue_fade")
    request(session, "MixNudge=+0.1")
    kwargs = frame._playback.start_mix_preview.call_args.kwargs
    assert kwargs["pre_seconds"] == 0.5
    assert kwargs["fade_seconds"] == 0.1
    assert kwargs["mix_at_seconds"] == 110
    assert request(session, "MixInfo").endswith("|przejscie")
    monkeypatch.setattr("sara.remote.mix_control.time.perf_counter", lambda: session.mix._deadline + 1)
    session.mix.tick()
    assert session.mix.preview == "brak"
    frame._stop_preview.assert_called()


def test_pure_session_validation():
    from sara.remote.mix_session import MixSession
    state = MixSession(duration=100, values={"cue": 0, "intro": 1, "outro": 2,
        "loop_start": 10, "loop_end": 9})
    assert state.validation_error() == "petla"
    state.values["intro"] = 0
    assert state.validation_error() == "kolejnosc"
