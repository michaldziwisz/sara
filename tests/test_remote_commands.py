from __future__ import annotations

import copy
import csv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sara.core.playlist import PlaylistItem, PlaylistItemStatus as Status, PlaylistKind, PlaylistModel
from sara.remote.commands import CommandSession, app_version
from sara.ui.services.auto_mix_tracker import AutoMixTracker


class Panel:
    def __init__(self, model):
        self.model = model
        self.selected = []
        self.focused = -1
        self.refresh = Mock()

    def get_selected_indices(self):
        return self.selected.copy()

    def get_focused_index(self):
        return self.focused

    def select_index(self, index):
        self.selected = [index]
        self.focused = index


class Frame:
    def __init__(self):
        self.panel = Panel(PlaylistModel("music", "Muzyka", items=[
            PlaylistItem("a", Path("a.wav"), "Tytuł", 125, artist="Żółw", cue_in_seconds=5),
            PlaylistItem("b", Path("b.wav"), "Drugi", 45, artist="Autor"),
        ]))
        self._playlists = {"music": self.panel}
        self._auto_mix_enabled = False
        self._alternate_play_next = False
        self._current_index = 0
        self._layout = SimpleNamespace(state=SimpleNamespace(order=["music"]))
        self._last_started_item_id = {}
        self._auto_mix_tracker = AutoMixTracker()
        self._playback = SimpleNamespace(contexts={}, auto_mix_state={},
                                         close_preloads=Mock(), schedule_next_preload=Mock())
        self._action_by_id = {10: "pause", 11: "stop", 12: "fade"}
        self._on_global_play_next = Mock()
        self._start_next_from_playlist = Mock(return_value=True)
        self._auto_mix_play_next = Mock(return_value=True)
        self._play_next_alternate = Mock(return_value=True)
        self._on_playlist_hotkey = Mock()
        self._announce_event = Mock()
        self._jingles = SimpleNamespace(_main_player=None, _overlay_players=[])

    def _get_current_music_panel(self):
        return self.panel

    def _get_playback_context(self, playlist_id):
        matches = [(key, ctx) for key, ctx in self._playback.contexts.items() if key[0] == playlist_id]
        return matches[-1] if matches else None

    def _set_auto_mix_enabled(self, enabled, **kwargs):
        self._auto_mix_enabled = enabled

    def _on_toggle_selection(self, playlist_id, item_id):
        if not self._auto_mix_enabled:
            self._playlists[playlist_id].model.toggle_selection(item_id)


def test_version_fallback_matches_project(monkeypatch):
    import importlib.metadata
    import tomllib
    from sara import __version__
    from sara.remote import commands

    with (Path(__file__).parents[1] / "pyproject.toml").open("rb") as stream:
        assert __version__ == tomllib.load(stream)["project"]["version"]
    # Przestarzałe metadane instalacji (tak było na głównej: 0.0.11) nie
    # mogą zmienić wersji podawanej w Helo.
    monkeypatch.setattr(importlib.metadata, "version", Mock(return_value="0.0.11"))
    assert commands.app_version() == __version__


def test_helo_and_batch_case_insensitive():
    session = CommandSession(Frame(), program_version="1.2.3")
    assert session.execute_line("hELo, STAT,LastIndex") == ["SARA v1.2.3", "0000001", "1"]
    assert app_version() == "0.0.37"


@pytest.mark.parametrize("command,action", [("Stop", "fade"), ("Instant Stop", "stop"), ("Pause", "pause")])
def test_control_uses_hotkey_path(command, action, monkeypatch):
    frame = Frame()
    from sara.ui.controllers.playlists import hotkeys
    run = Mock()
    monkeypatch.setattr(hotkeys, "run_playlist_action", run)
    session = CommandSession(frame)
    assert len(session.execute_line(command)[0]) == 7
    run.assert_called_once_with(frame, frame.panel, action)
    frame._announce_event.assert_not_called()


@pytest.mark.parametrize("command", ["Play", "Skip"])
@pytest.mark.parametrize("alternate,automix", [(False, False), (True, False), (False, True), (True, True)])
def test_play_and_skip_delegate_without_changing_mode(command, alternate, automix):
    frame = Frame()
    frame._alternate_play_next, frame._auto_mix_enabled = alternate, automix
    CommandSession(frame).execute_line(command)
    expected = frame._auto_mix_play_next if automix and not alternate else frame._start_next_from_playlist
    expected.assert_called_once_with(frame.panel)
    frame._on_global_play_next.assert_not_called()
    assert (frame._alternate_play_next, frame._auto_mix_enabled) == (alternate, automix)


def test_pause_already_paused_is_idempotent():
    frame = Frame()
    frame.panel.model.items[0].status = Status.PAUSED
    frame._playback.contexts[("music", "a")] = SimpleNamespace()
    assert CommandSession(frame).execute_line("Pause") == ["0000101"]
    frame._on_playlist_hotkey.assert_not_called()


def test_auto_commands():
    session = CommandSession(Frame())
    for command, enabled in [("AutoOn", True), ("AutoOn", True), ("AutoOff", False), ("AutoOff", False), ("Auto", True), ("Auto", False)]:
        assert session.execute_line(command)[0][1] == str(int(enabled))
        assert session.frame._auto_mix_enabled is enabled


def test_now_playing_times_and_indices():
    frame = Frame()
    session = CommandSession(frame)
    assert session.execute_line("This,Rem,Elap,CurrIndex,SelectIndex,Next") == ["", "0", "0", "-1", "-1", "Żółw - Tytuł"]
    item = frame.panel.model.items[0]
    item.status = Status.PLAYING
    item.update_progress(17.5)
    frame._last_started_item_id["music"] = "a"
    frame._playback.contexts[("music", "a")] = SimpleNamespace()
    assert session.execute_line("This,Rem,Elap,CurrIndex,Next") == ["Żółw - Tytuł", "107500", "12500", "0", "Autor - Drugi"]
    item.status = Status.PAUSED
    assert session.execute_line("Rem,Elap") == ["107500", "12500"]


def test_now_playing_ignores_writer_key_of_other_playlist():
    frame = Frame()
    other = Panel(PlaylistModel("other", "Inna", items=[PlaylistItem("c", Path("c.wav"), "Najnowszy", 10)]))
    frame._playlists["other"] = other
    frame._playback.contexts[("other", "c")] = SimpleNamespace()
    frame._playback.contexts[("music", "a")] = SimpleNamespace()
    frame._now_playing_writer = SimpleNamespace(_current_key=("other", "c"))
    assert CommandSession(frame).execute_line("This,CurrIndex") == ["Żółw - Tytuł", "0"]


def test_select_and_checktoggle_are_distinct_and_do_not_play():
    frame = Frame()
    session = CommandSession(frame)
    assert session.execute_line("SelectIndex=+") == ["0"]
    assert session.execute_line("SelectIndex=+") == ["1"]
    assert session.execute_line("SelectIndex=+") == ["1"]
    assert session.execute_line("CheckToggle") == ["1"]
    assert frame.panel.model.items[1].is_selected
    assert session.execute_line("CheckToggle") == ["0"]
    assert session.execute_line("SelectIndex=-") == ["0"]
    assert session.execute_line("SelectIndex=-") == ["0"]
    assert session.execute_line("SelectIndex=1") == ["1"]
    assert session.execute_line("SelectIndex") == ["1"]
    frame._on_global_play_next.assert_not_called()
    frame._on_playlist_hotkey.assert_not_called()


def test_focused_row_without_selection_can_be_queued_and_navigated():
    frame = Frame()
    frame.panel.focused = 0
    session = CommandSession(frame)
    assert session.execute_line("SelectIndex,CheckToggle") == ["-1", "1"]
    assert frame.panel.model.items[0].is_selected
    assert session.execute_line("SelectIndex=+") == ["1"]


def test_trackinfo_formats_and_delimiters():
    frame = Frame()
    item = frame.panel.model.items[0]
    item.artist = "Żółw|Kot\r\n"
    item.title = 'Tytuł, "Część"'
    item.is_selected = True
    item.break_after = True
    session = CommandSession(frame)
    rows = session.execute_line("TrackInfoEx=0-1")
    assert rows == ['0|1|pending|Żółw Kot  |Tytuł, "Część"|120000|1', '1|0|pending|Autor|Drugi|45000|0']
    for state in Status:
        item.status = state
        assert session.execute_line("TrackInfoEx=0-0")[0].split("|")[2] == state.name.lower()
    row = next(csv.reader(session.execute_line("TrackInfo=0-0")))
    assert row == ['0', '0', 'Żółw|Kot  ', 'Tytuł, "Część"', '', '120000', '0', '0', '', 'a.wav']


@pytest.mark.parametrize("command,expected", [
    ("missing", "ERR unknown"), ("Run=bad", "ERR unknown"), ("", "ERR unknown"),
    ("SelectIndex=1,Stat", "ERR syntax"), ("Play,SelectIndex=1", "ERR syntax"),
    ("TrackInfo", "ERR syntax"), ("TrackInfoEx=all", "ERR syntax"),
    ("SelectIndex=x", "ERR syntax"), ("SelectIndex=", "ERR syntax"),
    ("SelectIndex=99", "ERR range"), ("TrackInfo=1-0", "ERR range"),
    ("TrackInfoEx=0-10", "ERR range"), ("Play=yes", "ERR unknown"),
])
def test_errors_have_no_control_side_effects(command, expected):
    frame = Frame()
    assert CommandSession(frame).execute_line(command) == [expected]
    frame._on_global_play_next.assert_not_called()
    frame._on_playlist_hotkey.assert_not_called()


def test_empty_and_absent_playlist():
    frame = Frame()
    frame._playlists.clear()
    frame.panel = None
    session = CommandSession(frame)
    assert session.execute_line("This,Next,LastIndex,CurrIndex,SelectIndex,CheckToggle") == ["", "", "-1", "-1", "-1", "-1"]
    session.execute_line("Play")
    frame._on_global_play_next.assert_not_called()
    frame._start_next_from_playlist.assert_not_called()
    assert session.execute_line("TrackInfoEx=0-0") == ["ERR range"]
    assert session.execute_line("SelectIndex=+") == ["-1"]


def test_stat_dirty_is_per_client_and_progress_is_not_an_edit():
    frame = Frame()
    first, second = CommandSession(frame), CommandSession(frame)
    assert first.execute_line("Stat,Stat") == ["0000001", "0000000"]
    assert second.execute_line("Stat,Stat") == ["0000001", "0000000"]
    item = frame.panel.model.items[0]
    item.current_position = 3
    assert first.execute_line("Stat") == ["0000000"]
    item.is_selected = True
    assert first.execute_line("Stat,Stat") == ["0000001", "0000000"]
    assert second.execute_line("Stat") == ["0000001"]
    item.title = "Edycja z GUI"
    assert first.execute_line("Stat")[0][-1] == "1"
    frame.panel.model.items.reverse()
    assert first.execute_line("Stat")[0][-1] == "1"
    frame.panel.model.items.pop()
    assert first.execute_line("Stat")[0][-1] == "1"


def test_stat_playing_paused_cart_and_auto_bits():
    frame = Frame()
    session = CommandSession(frame)
    frame.panel.model.items[0].status = Status.PLAYING
    frame.panel.model.items[1].status = Status.PAUSED
    frame._playback.contexts = {("music", "a"): object(), ("music", "b"): object()}
    frame._jingles._overlay_players = [SimpleNamespace(is_playing=lambda: True)]
    frame._auto_mix_enabled = True
    assert session.execute_line("Stat,Stat") == ["1100111", "1100110"]


def test_next_uses_queue_automix_and_alternate_without_mutation():
    frame = Frame()
    session = CommandSession(frame)
    frame.panel.model.items[1].is_selected = True
    before = copy.deepcopy(frame.panel.model)
    assert session.execute_line("Next") == ["Autor - Drugi"]
    assert frame.panel.model == before
    frame._auto_mix_enabled = True
    frame._auto_mix_tracker.set_last_started("music", "b")
    before_tracker = copy.deepcopy(frame._auto_mix_tracker)
    assert session.execute_line("Next") == ["Żółw - Tytuł"]
    assert frame._auto_mix_tracker == before_tracker
    frame._alternate_play_next = True
    frame._auto_mix_enabled = False
    frame._playlists["other"] = Panel(PlaylistModel("other", "Inna", items=[PlaylistItem("x", Path("x.wav"), "Inna", 1)]))
    frame._layout.state.order.append("other")
    frame._current_index = 1
    assert session.execute_line("Next") == ["Inna"]
