"""Kontrakt klawiatury sprawdzany również z kodem bazowym 5207cf0."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sara.core.playlist import PlaylistItemStatus as Status
from sara.ui.controllers.playback.navigation import on_global_play_next
from sara.ui.controllers.playlists.hotkeys import handle_playlist_hotkey
from test_remote_main_playlist import main_frame, playing


def keyboard_frame():
    frame = main_frame()
    frame._layout.state.current_id = "second"
    panel = frame._playlists["second"]
    panel.selected, panel.focused = [0], 0
    frame._action_by_id = {1: "play", 2: "pause", 3: "stop", 4: "fade", 5: "break_toggle"}
    return frame, panel


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("key", ["SPACE", "F1"])
def test_keyboard_play_uses_active_not_remote_main(key, auto):
    frame, panel = keyboard_frame()
    frame._auto_mix_enabled = auto
    if key == "SPACE":
        on_global_play_next(frame, None)
    else:
        handle_playlist_hotkey(frame, SimpleNamespace(GetId=lambda: 1))
    expected = frame._auto_mix_play_next if auto else frame._start_next_from_playlist
    expected.assert_called_once_with(panel)
    assert frame._layout.state.current_id == "second"


@pytest.mark.parametrize("key", [2, 3, 4])
def test_keyboard_pause_stop_fade_use_active(key):
    frame, panel = keyboard_frame()
    item, ctx = playing(frame, "second")
    handle_playlist_hotkey(frame, SimpleNamespace(GetId=lambda: key))
    if key == 2:
        ctx.player.pause.assert_called_once()
        assert item.status is Status.PAUSED
        panel.refresh.assert_called_once_with()
        frame._set_auto_mix_enabled.assert_not_called()
    else:
        frame._stop_playlist_playback.assert_called_once_with(
            "second", mark_played=key == 4, fade_duration=2.5 if key == 4 else 0.0)
        assert frame._set_auto_mix_enabled.call_args.args == (False,)
    assert frame._layout.state.current_id == "second"


@pytest.mark.parametrize("initial", [(False, False), (True, True), (True, False), (False, True)])
def test_keyboard_break_multi_selection_keeps_original_semantics(initial):
    frame, panel = keyboard_frame()
    panel.selected = [0, 1]
    item, ctx = playing(frame, "second", index=1)
    for track, flag in zip(panel.model.items, initial):
        track.break_after = flag
    handle_playlist_hotkey(frame, SimpleNamespace(GetId=lambda: 5))
    assert [i.break_after for i in panel.model.items] == [not flag for flag in initial]
    panel.refresh.assert_called_once_with([0, 1], focus=True)
    if not initial[-1]:
        assert frame._active_break_item == {"second": "c"}
        frame._clear_mix_plan.assert_called_once_with("second", "d")
        frame._playback.update_mix_trigger.assert_called_once_with(
            "second", "d", mix_trigger_seconds=None, on_mix_trigger=None)
        frame._apply_mix_trigger_to_playback.assert_not_called()
    else:
        assert frame._active_break_item == {}
        frame._apply_mix_trigger_to_playback.assert_called_once_with(
            playlist_id="second", item=item, panel=panel)
    assert frame._layout.state.current_id == "second"


def test_keyboard_space_alternate_still_uses_existing_alternate_action():
    frame, panel = keyboard_frame()
    frame._alternate_play_next = True
    on_global_play_next(frame, None)
    frame._play_next_alternate.assert_called_once_with()
    frame._start_next_from_playlist.assert_not_called()
