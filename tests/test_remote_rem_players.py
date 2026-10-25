from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sara.core.mix_planner import MixPlan
from sara.core.playlist import PlaylistItem, PlaylistItemStatus as Status
from sara.remote.commands import CommandSession
from sara.ui.controllers.playback import loop
from sara.ui.playback.context import PlaybackContext
from sara.ui.playback.preview import PreviewContext
from test_remote_commands import Panel
from test_remote_main_playlist import main_frame
from test_remote_server import exchange, pump_until, remote


# Plan: plik 125 s, Cue 5 s, Segue 90,25 s od początku pliku.
# Pozycja 12,5 s od Cue: do końca 107500 ms, do przejścia 72750 ms.
REM_CASES = [
    pytest.param(90.25, False, False, 85.25, 2.5, 12.5, 72750, id="segue"),
    pytest.param(124.97, False, False, 85.25, 2.5, 12.5, 107500, id="near-end"),
    pytest.param(125.0, False, False, 85.25, 2.5, 12.5, 107500, id="at-end"),
    pytest.param(124.94, False, False, 85.25, 2.5, 12.5, 107440, id="outside-end-threshold"),
    pytest.param(None, False, False, 85.25, 2.5, 12.5, 107500, id="plan-without-trigger"),
    pytest.param(90.25, True, False, 85.25, 2.5, 12.5, 107500, id="break"),
    pytest.param(90.25, False, True, 85.25, 2.5, 12.5, 107500, id="loop"),
    pytest.param("absent", False, False, 85.25, 2.5, 12.5, 72750, id="no-plan-segue"),
    pytest.param("absent", False, False, None, 2.5, 12.5, 105000, id="no-plan-fade"),
    pytest.param("absent", False, False, None, 0.0, 12.5, 107500, id="no-plan-no-fade"),
    pytest.param(90.25, False, False, 85.25, 2.5, 100.0, 0, id="past-mix"),
]


def add_context(frame, pid="music", index=0, slot=1, status=Status.PLAYING):
    item = frame._playlists[pid].model.items[index]
    item.status = status
    context = PlaybackContext(player=Mock(), path=item.path, device_id="output", slot_index=slot)
    frame._playback.contexts[(pid, item.id)] = context
    return item, context


def remaining_frame(mix_at=90.25, break_after=False, loop_enabled=False,
                    segue=85.25, fade=2.5, position=12.5):
    frame = main_frame()
    item, _ = add_context(frame)
    item.current_position = position
    item.segue_seconds = segue
    item.break_after = break_after
    item.loop_start_seconds, item.loop_end_seconds = 10.0, 20.0
    item.loop_enabled = loop_enabled
    frame._fade_duration = fade
    frame._mix_plans = {}
    if mix_at != "absent":
        frame._mix_plans[("music", "a")] = MixPlan(mix_at, fade, 5.0, 120.0, True)
    return frame, item


@pytest.mark.parametrize("mix_at,break_after,loop_enabled,segue,fade,position,expected", REM_CASES)
def test_rem_matches_shortcut_resolver(mix_at, break_after, loop_enabled, segue, fade, position, expected,
                                     monkeypatch):
    frame, item = remaining_frame(mix_at, break_after, loop_enabled, segue, fade, position)
    # Prawdziwa funkcja skrótu; jedynie panel GUI jest atrapą.
    monkeypatch.setattr(loop, "PlaylistPanel", Panel)
    frame._active_playlist_item = lambda model: loop.active_playlist_item(frame, model)
    resolved = loop.resolve_remaining_playback(frame)
    assert resolved is not None
    playlist, active_item, seconds = resolved
    assert playlist is frame.panel.model and active_item is item
    assert round(seconds * 1000) == expected
    assert CommandSession(frame).execute_line("Rem,Elap") == [str(expected), str(round(position * 1000))]


def test_rem_calls_existing_total_resolver_only_for_rem(monkeypatch):
    frame, item = remaining_frame()
    resolver = Mock(return_value=20.123)
    monkeypatch.setattr(loop, "_resolve_on_air_total_seconds", resolver)
    session = CommandSession(frame)
    assert session.execute_line("Elap") == ["12500"]
    resolver.assert_not_called()
    assert session.execute_line("Rem") == ["7623"]
    resolver.assert_called_once_with(frame, frame.panel.model, item)


def test_rem_keeps_current_selection_and_main_playlist():
    frame, _ = remaining_frame()
    incoming, _ = add_context(frame, index=1, slot=0)
    incoming.current_position = 1.0
    add_context(frame, pid="second", slot=5)
    frame._layout.state.current_id = "second"
    session = CommandSession(frame)
    frame._now_playing_writer = SimpleNamespace(_current_key=("music", "a"))
    assert session.execute_line("This,Rem") == ["Żółw - Tytuł", "72750"]
    frame._now_playing_writer._current_key = ("second", "c")
    assert session.execute_line("This,Rem") == ["Autor - Drugi", "41500"]
    assert frame._layout.state.current_id == "second"


def test_rem_hold_uses_full_length_and_release_restores_mix():
    frame, item = remaining_frame()
    session = CommandSession(frame)
    assert session.execute_line("Rem") == ["72750"]
    assert session.execute_line("Hold=1") == ["1,trzyma"]
    assert item.break_after
    assert session.execute_line("Rem") == ["107500"]
    assert session.execute_line("Hold=0") == ["0,trzyma"]
    assert not item.break_after
    assert session.execute_line("Rem") == ["72750"]


def test_rem_and_players_without_main_playback():
    frame = main_frame()
    add_context(frame, pid="second", slot=3)
    session = CommandSession(frame)
    assert session.execute_line("Rem,Elap,Players") == ["0", "0", "-"]
    frame._playlists.clear()
    assert session.execute_line("Rem,Elap,Players") == ["0", "0", "-"]


@pytest.mark.parametrize("status", [Status.PLAYING, Status.PAUSED])
def test_players_one_based_including_pause(status):
    frame, item = remaining_frame()
    item.status = status
    assert CommandSession(frame).execute_line("pLaYeRs,Rem,Elap") == ["2", "72750", "12500"]


def test_players_during_mix_sorted_unique_and_readonly():
    frame = main_frame()
    add_context(frame, index=0, slot=1)
    add_context(frame, index=1, slot=0)
    frame.panel.model.items.append(PlaylistItem("e", Path("e.wav"), "Trzeci", 30))
    add_context(frame, index=2, slot=1)
    session = CommandSession(frame)
    session.execute_line("Stat")
    before = copy.deepcopy(frame.panel.model)
    contexts = frame._playback.contexts.copy()
    assert session.execute_line("Players,Stat") == ["1,2", "1000000"]
    assert frame.panel.model == before
    assert frame._playback.contexts == contexts
    for context in contexts.values():
        assert context.player.mock_calls == []
    frame._start_next_from_playlist.assert_not_called()
    frame._stop_playlist_playback.assert_not_called()
    frame._announce_event.assert_not_called()
    assert frame._layout.state.current_id == "news"


def test_players_sort_numerically_not_lexically():
    frame = main_frame()
    add_context(frame, index=0, slot=9)
    add_context(frame, index=1, slot=1)
    assert CommandSession(frame).execute_line("Players") == ["2,10"]


def test_players_ignore_other_playlist_and_pfl():
    frame = main_frame()
    add_context(frame, slot=1)
    add_context(frame, pid="second", slot=3)
    preview = PreviewContext(players=[Mock()], device_id="pfl", item_path=Path("pfl.wav"))
    frame._playback._preview_context = preview
    frame._playback.preview_context = preview
    frame._now_playing_writer = SimpleNamespace(_current_key=("second", "c"))
    frame._layout.state.current_id = "second"
    session = CommandSession(frame)
    assert session.execute_line("Players") == ["2"]
    del frame._playback.contexts[("music", "a")]
    assert session.execute_line("Players") == ["-"]
    frame._playback.contexts.clear()
    assert session.execute_line("Players") == ["-"]
    assert preview.players[0].mock_calls == []
    assert frame._playback._preview_context is preview


def test_players_use_configured_main_not_focus_or_first_playlist():
    frame = main_frame()
    add_context(frame, slot=0)
    add_context(frame, pid="second", slot=2)
    frame._settings.get_remote_main_playlist = lambda: "second"
    frame._layout.state.current_id = "music"
    assert CommandSession(frame).execute_line("Players") == ["3"]
    assert frame._layout.state.current_id == "music"


@pytest.mark.parametrize("command,expected", [
    ("Players=", "ERR unknown"), ("Players=1", "ERR unknown"),
    ("Players=1,Stat", "ERR syntax"),
])
def test_players_reject_equals(command, expected):
    frame = main_frame()
    assert CommandSession(frame).execute_line(command) == [expected]
    assert frame._playback.contexts == {}
    frame._start_next_from_playlist.assert_not_called()


def test_rem_players_real_socket_single_line_and_gui_thread(remote, monkeypatch):
    frame, callbacks, _, server = remote
    item, _ = add_context(frame, index=0, slot=1)
    add_context(frame, index=1, slot=0)
    item.current_position = 12.5
    frame._now_playing_writer = SimpleNamespace(_current_key=("music", "a"))
    frame._mix_plans = {("music", "a"): MixPlan(90.25, 2.5, 5.0, 120.0, True)}
    threads = []
    execute = CommandSession._execute

    def traced_execute(self, command):
        threads.append(threading.current_thread())
        return execute(self, command)

    monkeypatch.setattr(CommandSession, "_execute", traced_execute)
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(exchange, server.address, b"Players,Rem,Elap\r\nPlayers=1\n", 4)
        result = pump_until([request], callbacks)[0]
    assert result == [b"1,2\r\n", b"72750\r\n", b"12500\r\n", b"ERR unknown\r\n"]
    assert threads == [threading.main_thread()] * 4
