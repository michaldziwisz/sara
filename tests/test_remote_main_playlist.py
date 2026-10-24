from __future__ import annotations

from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest

from sara.core.config import SettingsManager
from sara.core.playlist import PlaylistItem, PlaylistItemStatus as Status, PlaylistKind, PlaylistModel
from sara.remote.commands import CommandSession
from sara.ui.controllers.playback.navigation import on_global_play_next
from sara.ui.controllers.playlists.hotkeys import handle_playlist_hotkey
from test_remote_commands import Frame, Panel


def main_frame():
    frame = Frame()
    second = Panel(PlaylistModel("second", "Druga", items=[
        PlaylistItem("c", Path("c.wav"), "Trzeci", 90),
        PlaylistItem("d", Path("d.wav"), "Czwarty", 70),
    ]))
    news = Panel(PlaylistModel("news", "Wiadomości", kind=PlaylistKind.NEWS))
    frame._playlists.update(second=second, news=news)
    frame._layout.state.order = ["news", "music", "second"]
    frame._layout.state.current_id = "news"
    frame._layout.set_current = lambda pid: setattr(frame._layout.state, "current_id", pid)
    frame._settings = SimpleNamespace(get_remote_main_playlist=lambda: "")
    frame._get_current_music_panel = lambda: next((p for pid, p in frame._playlists.items()
        if pid == frame._layout.state.current_id and p.model.kind is PlaylistKind.MUSIC), None)
    frame._start_next_from_playlist = Mock(return_value=True)
    frame._auto_mix_play_next = Mock(return_value=True)
    frame._play_next_alternate = Mock(return_value=True)
    frame._active_news_panel = lambda: (None, None)
    frame._on_global_play_next = MethodType(on_global_play_next, frame)
    frame._on_playlist_hotkey = MethodType(handle_playlist_hotkey, frame)
    frame._manual_fade_duration = lambda playlist, item: 2.5
    frame._stop_playlist_playback = Mock()
    frame._set_auto_mix_enabled = Mock(side_effect=lambda enabled, **kw: setattr(frame, "_auto_mix_enabled", enabled))
    frame._active_break_item = {}
    frame._clear_mix_plan = Mock()
    frame._apply_mix_trigger_to_playback = Mock()
    frame._playback.update_mix_trigger = Mock()
    for panel in frame._playlists.values():
        panel.mark_item_status = Mock()
        panel.update_item_display = Mock()
    return frame


def playing(frame, pid="music", index=0):
    item = frame._playlists[pid].model.items[index]
    item.status = Status.PLAYING
    context = SimpleNamespace(player=Mock())
    frame._playback.contexts[(pid, item.id)] = context
    return item, context


def test_news_active_all_commands_target_main_without_activation():
    frame = main_frame()
    item, context = playing(frame)
    playing(frame, "second")
    frame._now_playing_writer = SimpleNamespace(_current_key=("second", "c"))
    session = CommandSession(frame)
    assert session.execute_line("Stat,This,CurrIndex,LastIndex,Elap,Rem") == [
        "1000001", "Żółw - Tytuł", "0", "1", "0", "120000"]
    assert session.execute_line("SelectIndex=+") == ["0"]
    assert session.execute_line("CheckToggle") == ["1"]
    assert item.is_selected
    assert session.execute_line("Next") == ["Żółw - Tytuł"]
    assert session.execute_line("TrackInfoEx=0-0")[0].startswith("0|1|pending|Żółw|")
    assert "Tytuł" in session.execute_line("TrackInfo=0-0")[0]
    session.execute_line("Pause")
    context.player.pause.assert_called_once()
    session.execute_line("Stop")
    frame._stop_playlist_playback.assert_called_once_with("music", mark_played=True, fade_duration=2.5)
    assert frame._layout.state.current_id == "news"


def test_configured_second_selection_leaves_first_active():
    frame = main_frame()
    frame._layout.state.current_id = "music"
    frame._settings.get_remote_main_playlist = lambda: "second"
    session = CommandSession(frame)
    assert session.execute_line("SelectIndex=+") == ["0"]
    assert session.execute_line("SelectIndex=+") == ["1"]
    assert frame._playlists["second"].selected == [1]
    assert frame.panel.selected == []
    assert frame._layout.state.current_id == "music"


@pytest.mark.parametrize("configured", ["", "deleted", "news"])
def test_missing_or_nonmusic_main_uses_layout_order(configured):
    frame = main_frame()
    frame._settings.get_remote_main_playlist = lambda: configured
    frame._layout.state.order = ["gone", "news", "second", "music"]
    assert CommandSession(frame).execute_line("SelectIndex=+") == ["0"]
    assert frame._playlists["second"].selected == [0]
    assert frame._layout.state.current_id == "news"


def test_stat_does_not_report_other_playlist_playback():
    frame = main_frame()
    playing(frame, "second")
    assert CommandSession(frame).execute_line("Stat,This,CurrIndex") == ["0000001", "", "-1"]


def test_main_setting_roundtrip_and_invalid_type(tmp_path):
    settings = SettingsManager(tmp_path / "settings.yaml")
    assert settings.get_remote_main_playlist() == ""
    settings.set_remote_main_playlist("second")
    settings.save()
    assert SettingsManager(settings.config_path).get_remote_main_playlist() == "second"
    for value in [None, [], 123, True]:
        settings._data["remote"]["main_playlist"] = value
        assert settings.get_remote_main_playlist() == ""


@pytest.mark.parametrize("command", ["Play", "Skip"])
@pytest.mark.parametrize("automix", [False, True])
def test_play_uses_main_music_path(command, automix):
    frame = main_frame()
    frame._auto_mix_enabled = automix
    CommandSession(frame).execute_line(command)
    target = frame._auto_mix_play_next if automix else frame._start_next_from_playlist
    target.assert_called_once_with(frame.panel)
    assert frame._layout.state.current_id == "news"


def test_auto_on_starts_main_not_active_playlist():
    from sara.ui.controllers.playback.automix import set_auto_mix_enabled
    frame = main_frame()
    frame._set_auto_mix_enabled = MethodType(set_auto_mix_enabled, frame)
    frame._preferred_auto_mix_index = lambda panel, count: 0
    frame._auto_mix_start_index = Mock(return_value=True)
    CommandSession(frame).execute_line("AutoOn")
    frame._auto_mix_start_index.assert_called_once_with(frame.panel, 0, restart_playing=False)
    assert frame._layout.state.current_id == "news"

@pytest.mark.parametrize("command,action", [("Stop", "fade"), ("Instant Stop", "stop"), ("Pause", "pause")])
def test_control_targets_configured_second_not_active_first(command, action):
    frame = main_frame()
    frame._layout.state.current_id = "music"
    frame._settings.get_remote_main_playlist = lambda: "second"
    first, first_ctx = playing(frame)
    second, second_ctx = playing(frame, "second")
    CommandSession(frame).execute_line(command)
    if action == "pause":
        second_ctx.player.pause.assert_called_once()
        first_ctx.player.pause.assert_not_called()
    else:
        assert frame._stop_playlist_playback.call_args.args == ("second",)
    assert frame._layout.state.current_id == "music"


def test_alternate_remote_keeps_rotation_without_changing_active_panel():
    frame = main_frame()
    frame._layout.state.order = ["music", "second"]
    frame._layout.state.current_id = "news"
    frame._current_index = 0
    frame._alternate_play_next = True
    session = CommandSession(frame)
    session.execute_line("Play")
    assert frame._start_next_from_playlist.call_args.args == (frame.panel,)
    assert frame._current_index == 1
    session.execute_line("Play")
    assert frame._start_next_from_playlist.call_args.args == (frame._playlists["second"],)
    assert frame._current_index == 0
    assert frame._layout.state.current_id == "news"
