"""Play ze stołu w trybie ręcznym działa jak Enter (swap_play_select) w SARZE."""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from sara.core.playlist import PlaylistItemStatus as Status
from sara.remote.commands import CommandSession
from test_remote_main_playlist import main_frame, playing


def frame_with_direct():
    frame = main_frame()
    frame._play_item_direct = Mock(return_value=True)
    return frame


def test_manual_play_starts_highlighted_track_like_enter():
    frame = frame_with_direct()
    frame.panel.focused = 1
    CommandSession(frame).execute_line("Play")
    frame._play_item_direct.assert_called_once_with("music", "b")
    frame._start_next_from_playlist.assert_not_called()
    assert frame._layout.state.current_id == "news"


def test_manual_play_with_queue_plays_queue_in_order():
    frame = frame_with_direct()
    frame.panel.model.items[1].is_selected = True
    frame.panel.focused = 0
    CommandSession(frame).execute_line("Play")
    # play_item_direct sam przechodzi do kolejki (start_next ignore_ui_selection)
    frame._play_item_direct.assert_called_once_with("music", "b")


def test_manual_play_does_not_restart_highlighted_playing_track():
    frame = frame_with_direct()
    playing(frame, index=0)
    frame.panel.focused = 0
    CommandSession(frame).execute_line("Play")
    frame._play_item_direct.assert_not_called()
    frame._start_next_from_playlist.assert_not_called()


def test_manual_play_without_highlight_falls_back_to_play_next():
    frame = frame_with_direct()
    frame.panel.focused = -1
    CommandSession(frame).execute_line("Play")
    frame._play_item_direct.assert_not_called()
    frame._start_next_from_playlist.assert_called_once_with(frame.panel)


@pytest.mark.parametrize("automix,alternate", [(True, False), (False, True)])
def test_automix_and_alternate_keep_play_next(automix, alternate):
    frame = frame_with_direct()
    frame._auto_mix_enabled = automix
    frame._alternate_play_next = alternate
    frame._layout.state.order = ["music", "second"]
    frame._current_index = 0
    frame.panel.focused = 1
    CommandSession(frame).execute_line("Play")
    frame._play_item_direct.assert_not_called()


def test_skip_stays_play_next_in_manual_mode():
    frame = frame_with_direct()
    frame.panel.focused = 1
    CommandSession(frame).execute_line("Skip")
    frame._play_item_direct.assert_not_called()
    frame._start_next_from_playlist.assert_called_once_with(frame.panel)


def test_manual_play_targets_main_not_active_playlist():
    frame = frame_with_direct()
    frame._layout.state.current_id = "music"
    frame._settings.get_remote_main_playlist = lambda: "second"
    frame._playlists["second"].focused = 1
    frame.panel.focused = 0
    CommandSession(frame).execute_line("Play")
    frame._play_item_direct.assert_called_once_with("second", "d")
    assert frame._layout.state.current_id == "music"


def test_real_play_item_direct_queue_and_highlight(tmp_path, monkeypatch):
    """Prawdziwa ścieżka Entera: kolejka gra po kolei, bez kolejki podświetlony."""
    from sara.ui import main_frame as main_frame_module
    from sara.ui.main_frame import MainFrame

    frame = frame_with_direct()
    real = MainFrame.__new__(MainFrame)
    real._playlists = frame._playlists
    real._get_playlist_model = lambda pid: frame._playlists[pid].model
    real._auto_mix_enabled = False
    real._playlist_has_selection = lambda pid: any(i.is_selected for i in frame._playlists[pid].model.items)
    started = []
    real._start_next_from_playlist = lambda panel, **kw: started.append(("queue", kw)) or True
    monkeypatch.setattr(main_frame_module, "PlaylistPanel", type(frame.panel))
    monkeypatch.setattr("sara.ui.controllers.playback.flow.start_playback",
                        lambda fr, panel, item, **kw: started.append(("item", item.id, kw)) or True)
    real._last_started_item_id = {}
    real._announce_event = Mock()
    real._swap_play_select = True
    real._format_track_name = lambda item: item.title
    real._refresh_selection_display = Mock()
    frame._play_item_direct = real._play_item_direct
    frame.panel.focused = 1
    CommandSession(frame).execute_line("Play")
    assert started == [("item", "b", {"restart_playing": True})]
    started.clear()
    frame.panel.model.items[0].is_selected = True
    frame.panel.focused = 1
    CommandSession(frame).execute_line("Play")
    assert started == [("queue", {"ignore_ui_selection": True, "advance_focus": False})]
