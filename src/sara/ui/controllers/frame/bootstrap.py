"""MainFrame bootstrap helpers."""

from __future__ import annotations

import wx

from sara.audio.engine import AudioEngine
from sara.core.app_state import AppState, PlaylistFactory
from sara.core.config import SettingsManager
from sara.core.env import resolve_output_dir
from sara.core.i18n import gettext as _, set_language
from sara.ui.announcement_service import AnnouncementService
from sara.ui.auto_mix_tracker import AutoMixTracker
from sara.ui.clipboard_service import PlaylistClipboard
from sara.ui.jingle_controller import JingleController
from sara.ui.playback_controller import PlaybackController
from sara.ui.playlist_layout import PlaylistLayoutManager
from sara.ui.services.now_playing import NowPlayingWriter
from sara.ui.services.playback_logging import PlayedTracksLogger
from sara.ui.undo_manager import UndoManager


def init_settings(frame, settings: SettingsManager | None) -> None:
    frame._settings = settings or SettingsManager()
    set_language(frame._settings.get_language())
    if not frame._settings.config_path.exists():
        frame._settings.save()


def init_playlist_state(frame, state: AppState | None) -> None:
    frame._playlists = {}
    frame._playlist_wrappers = {}
    frame._playlist_headers = {}
    frame._playlist_titles = {}
    frame._layout = PlaylistLayoutManager()
    frame._current_index = 0
    frame._state = state or AppState()
    frame._playlist_factory = PlaylistFactory()


def init_audio_controllers(frame) -> None:
    frame._audio_engine = AudioEngine()
    frame._playback = PlaybackController(frame._audio_engine, frame._settings, frame._announce_event)
    frame._jingles_path = frame._settings.config_path.parent / "jingles.sarajingles"
    frame._jingles = JingleController(
        frame._audio_engine,
        frame._settings,
        frame._announce_event,
        set_path=frame._jingles_path,
    )


def init_command_ids(frame) -> None:
    frame._play_next_id = wx.NewIdRef()
    frame._add_tracks_id = wx.NewIdRef()
    frame._assign_device_id = wx.NewIdRef()
    frame._auto_mix_toggle_id = wx.NewIdRef()
    frame._loop_playback_toggle_id = wx.NewIdRef()
    frame._loop_info_id = wx.NewIdRef()
    frame._track_remaining_id = wx.NewIdRef()
    frame._remove_playlist_id = wx.NewIdRef()
    frame._manage_playlists_id = wx.NewIdRef()
    frame._cut_id = wx.NewIdRef()
    frame._copy_id = wx.NewIdRef()
    frame._paste_id = wx.NewIdRef()
    frame._delete_id = wx.NewIdRef()
    frame._mark_as_song_id = wx.NewIdRef()
    frame._mark_as_spot_id = wx.NewIdRef()
    frame._move_up_id = wx.NewIdRef()
    frame._move_down_id = wx.NewIdRef()
    frame._undo_id = wx.NewIdRef()
    frame._redo_id = wx.NewIdRef()
    frame._shortcut_editor_id = wx.NewIdRef()
    frame._jingles_manage_id = wx.NewIdRef()


def init_runtime_state(frame) -> None:
    frame._output_dir = resolve_output_dir()
    frame._played_tracks_logger = PlayedTracksLogger(frame._settings, output_dir=frame._output_dir)
    frame._now_playing_writer = NowPlayingWriter(frame._settings, output_dir=frame._output_dir)
    frame._playlist_hotkey_defaults = frame._settings.get_playlist_shortcuts()
    frame._playlist_action_ids = {}
    frame._action_by_id = {}
    frame._shortcut_menu_items = {}
    frame._auto_mix_enabled = False
    frame._alternate_play_next = frame._settings.get_alternate_play_next()
    frame._swap_play_select = frame._settings.get_swap_play_select()
    frame._auto_remove_played = frame._settings.get_auto_remove_played()
    frame._focus_playing_track = frame._settings.get_focus_playing_track()
    frame._intro_alert_seconds = frame._settings.get_intro_alert_seconds()
    frame._track_end_alert_seconds = frame._settings.get_track_end_alert_seconds()
    frame._clipboard = PlaylistClipboard()
    frame._undo_manager = UndoManager(frame._apply_undo_callback)
    frame._focus_lock = frame._layout.state.focus_lock
    frame._intro_alert_players = []
    frame._track_end_alert_players = []
    frame._last_started_item_id = {}
    frame._last_music_playlist_id = None
    frame._active_folder_preview = None
    frame._active_break_item = {}
    frame._mix_trigger_points = {}
    frame._mix_plans = {}
    frame._auto_mix_tracker = AutoMixTracker()
    frame._auto_mix_busy = {}
    frame._last_focus_index = {}


def init_ui(frame) -> None:
    frame.CreateStatusBar()
    frame.SetStatusText(_("Ready"))
    frame._announcer = AnnouncementService(frame._settings, status_callback=frame.SetStatusText)
    wx.ToolTip.Enable(False)
    frame.SetToolTip(None)
    frame._fade_duration = max(frame._settings.get_playback_fade_seconds(), 0.0)
    frame._create_menu_bar()
    frame._create_ui()
    frame._register_accessibility()
    frame._configure_accelerators()
    frame._global_shortcut_blocked = False
    frame.Bind(wx.EVT_CLOSE, frame._on_close)
