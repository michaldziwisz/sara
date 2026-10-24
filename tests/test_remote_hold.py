from __future__ import annotations

from types import MethodType
from unittest.mock import Mock

import pytest

from sara.remote.commands import CommandSession
from sara.ui.controllers.playback.finish import handle_playback_finished
from sara.ui.mix_runtime.triggers import apply_mix_trigger_to_playback
from test_remote_main_playlist import main_frame, playing


def hold_frame(automix=True):
    frame = main_frame()
    frame._auto_mix_enabled = automix
    frame._auto_remove_played = False
    frame._playlist_has_selection = lambda pid: any(i.is_selected for i in frame._playlists[pid].model.items)
    frame._mix_plans = {}
    frame.triggers = {}
    frame._clear_mix_plan = lambda pid, iid: frame._mix_plans.pop((pid, iid), None)
    def update(pid, iid, *, mix_trigger_seconds, on_mix_trigger):
        frame.triggers[(pid, iid)] = (mix_trigger_seconds, on_mix_trigger)
        return True
    frame._playback.update_mix_trigger = Mock(side_effect=update)
    frame._register_mix_plan = lambda pid, iid, **kw: frame._mix_plans.update({(pid, iid): kw})
    frame._resolve_mix_timing = lambda item, **kw: (item.segue_seconds, 2.0, item.cue_in_seconds or 0, item.effective_duration_seconds)
    frame._supports_mix_trigger = lambda player: True
    frame._auto_mix_now_from_callback = Mock()
    frame._apply_mix_trigger_to_playback = MethodType(apply_mix_trigger_to_playback, frame)
    frame.panel.model.items[0].segue_seconds = 118.0
    item, ctx = playing(frame)
    ctx.player.get_length_seconds.return_value = 125
    frame._apply_mix_trigger_to_playback(playlist_id="music", item=item, panel=frame.panel)
    return frame, item, ctx


@pytest.mark.parametrize("automix", [True, False])
def test_hold_removes_trigger_and_finish_stays_stopped(automix):
    frame, item, ctx = hold_frame(automix)
    frame.panel.model.items[1].is_selected = True
    session = CommandSession(frame)
    assert session.execute_line("Hold=1") == ["1,trzyma"]
    assert item.break_after
    assert frame.triggers[("music", "a")] == (None, None)
    assert ("music", "a") not in frame._mix_plans
    assert frame._playback.auto_mix_state[("music", "a")] == "break_halt"
    handle_playback_finished(frame, "music", "a")
    assert session.execute_line("Hold") == ["1,zatrzymane"]
    assert not frame._playback.contexts
    assert frame.panel.model.break_resume_index == 1
    assert session.execute_line("Hold=0") == ["0,brak"]
    assert frame.panel.model.break_resume_index == 1
    assert not item.break_after
    frame._auto_mix_play_next.assert_not_called()
    frame._start_next_from_playlist.assert_not_called()


@pytest.mark.parametrize("automix", [True, False])
def test_release_restores_exact_segue_trigger_without_start(automix):
    frame, item, ctx = hold_frame(automix)
    before = frame.triggers[("music", "a")][0]
    session = CommandSession(frame)
    assert session.execute_line("Hold=1") == ["1,trzyma"]
    assert session.execute_line("Hold=0") == ["0,trzyma"]
    assert not item.break_after
    assert frame.triggers[("music", "a")][0] == before == 118.0
    callback = frame.triggers[("music", "a")][1]
    callback()
    frame._auto_mix_now_from_callback.assert_called_once_with("music", "a")
    frame._start_next_from_playlist.assert_not_called()
    frame._auto_mix_play_next.assert_not_called()


def test_release_preserves_manual_break():
    frame, item, ctx = hold_frame()
    item.break_after = True
    frame._active_break_item["music"] = "a"
    frame._playback.auto_mix_state[("music", "a")] = "break_halt"
    frame._apply_mix_trigger_to_playback(playlist_id="music", item=item, panel=frame.panel)
    session = CommandSession(frame)
    assert session.execute_line("Hold=1") == ["1,trzyma"]
    assert session.execute_line("Hold=0") == ["0,trzyma"]
    assert item.break_after
    assert frame.triggers[("music", "a")] == (None, None)
    assert frame._active_break_item == {"music": "a"}


def test_hold_during_transition_protects_incoming_without_stopping():
    frame, outgoing, old = hold_frame()
    incoming, new = playing(frame, index=1)
    session = CommandSession(frame)
    assert session.execute_line("Hold=1") == ["1,za_pozno"]
    assert set(frame._playback.contexts) == {("music", "a"), ("music", "b")}
    assert incoming.break_after and not outgoing.break_after
    assert frame.triggers[("music", "b")] == (None, None)
    frame._stop_playlist_playback.assert_not_called()
    old.player.stop.assert_not_called()
    new.player.stop.assert_not_called()
    handle_playback_finished(frame, "music", "a")
    assert session.execute_line("Hold") == ["1,trzyma"]
    assert incoming.break_after


def test_hold_is_shared_idempotent_and_checked_after_play():
    frame, item, ctx = hold_frame()
    first, second = CommandSession(frame), CommandSession(frame)
    assert first.execute_line("Hold=1") == ["1,trzyma"]
    count = frame._playback.update_mix_trigger.call_count
    assert second.execute_line("hOlD=1") == ["1,trzyma"]
    assert frame._playback.update_mix_trigger.call_count == count
    def start(panel):
        handle_playback_finished(frame, "music", "a")
        playing(frame, index=1)
        return True
    frame._auto_mix_play_next = Mock(side_effect=start)
    second.execute_line("Play")
    assert frame.panel.model.items[1].break_after
    assert first.execute_line("Hold") == ["1,trzyma"]


def test_each_command_checks_new_context_even_readonly():
    frame, item, ctx = hold_frame()
    session = CommandSession(frame)
    session.execute_line("Hold=1")
    handle_playback_finished(frame, "music", "a")
    playing(frame, index=1)
    session.execute_line("Helo")
    assert frame.panel.model.items[1].break_after


def test_hold_main_is_not_active_and_does_not_touch_other_context():
    frame, item, ctx = hold_frame()
    other, other_ctx = playing(frame, "second")
    assert frame._layout.state.current_id == "news"
    assert CommandSession(frame).execute_line("Hold=1") == ["1,trzyma"]
    assert item.break_after and not other.break_after
    assert frame._layout.state.current_id == "news"


@pytest.mark.parametrize("value", ["", "true", "2", "-1", "01"])
def test_hold_invalid_value_is_syntax_error(value):
    frame, item, ctx = hold_frame()
    assert CommandSession(frame).execute_line("Hold=" + value) == ["ERR syntax"]
    assert not item.break_after


def test_hold_without_music():
    frame = main_frame()
    frame._playlists = {"news": frame._playlists["news"]}
    session = CommandSession(frame)
    assert session.execute_line("Hold=1") == ["1,brak"]
    assert session.execute_line("Hold") == ["1,brak"]
    assert session.execute_line("Hold=0") == ["0,brak"]

@pytest.mark.parametrize("automix", [True, False])
def test_explicit_next_after_release_starts_resume_item(automix):
    from sara.ui.controllers.playback.flow import start_next_from_playlist
    from sara.ui.controllers.playback.automix import auto_mix_play_next
    frame, item, ctx = hold_frame(automix)
    session = CommandSession(frame)
    session.execute_line("Hold=1")
    handle_playback_finished(frame, "music", "a")
    assert session.execute_line("Hold=0") == ["0,brak"]
    assert frame.panel.model.break_resume_index == 1
    if automix:
        frame._auto_mix_busy = {}
        frame._auto_mix_play_next = MethodType(auto_mix_play_next, frame)
        frame._auto_mix_start_index = Mock(return_value=True)
    else:
        frame._start_next_from_playlist = MethodType(start_next_from_playlist, frame)
        frame._playback.get_context = frame._get_playback_context
        frame._start_playback = Mock(return_value=True)
        frame._format_track_name = lambda track: track.title
        frame._focus_playing_track = False
    session.execute_line("Play")
    if automix:
        frame._auto_mix_start_index.assert_called_once_with(frame.panel, 1, restart_playing=False)
    else:
        assert frame._start_playback.call_args.args == (frame.panel, frame.panel.model.items[1])


def test_releasing_own_break_keeps_incoming_manual_break_state():
    frame, item, ctx = hold_frame()
    session = CommandSession(frame)
    session.execute_line("Hold=1")
    incoming, new = playing(frame, index=1)
    incoming.break_after = True
    frame._active_break_item["music"] = incoming.id
    frame._playback.auto_mix_state[("music", incoming.id)] = "break_halt"
    assert session.execute_line("Hold=0") == ["0,trzyma"]
    assert not item.break_after
    assert incoming.break_after
    assert frame._active_break_item == {"music": incoming.id}
    assert frame._playback.auto_mix_state[("music", incoming.id)] == "break_halt"


def test_changing_main_moves_hold_without_start():
    frame, item, ctx = hold_frame()
    other, other_ctx = playing(frame, "second")
    other_ctx.player.get_length_seconds.return_value = 90
    session = CommandSession(frame)
    session.execute_line("Hold=1")
    frame._settings.get_remote_main_playlist = lambda: "second"
    assert session.execute_line("Hold") == ["1,trzyma"]
    assert other.break_after and not item.break_after
    assert frame.triggers[("music", "a")][0] == 118.0
    frame._start_next_from_playlist.assert_not_called()
    frame._auto_mix_play_next.assert_not_called()
