"""Main window of the SARA application."""

from __future__ import annotations

from importlib.resources import as_file, files
from dataclasses import dataclass
import logging
import os
import tempfile
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import wx

from sara.audio.engine import AudioEngine, Player
from sara.core.app_state import AppState, PlaylistFactory
from sara.core.config import SettingsManager
from sara.core.i18n import gettext as _, set_language
from sara.core.hotkeys import HotkeyAction
from sara.core.media_metadata import (
    AudioMetadata,
    extract_metadata,
    is_supported_audio_file,
    save_loop_metadata,
    save_mix_metadata,
    save_replay_gain_metadata,
)
from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistKind, PlaylistModel
from sara.core.shortcuts import get_shortcut
from sara.ui.undo import InsertOperation, MoveOperation, RemoveOperation, UndoAction
from sara.ui.undo_manager import UndoManager
from sara.ui.new_playlist_dialog import NewPlaylistDialog
from sara.ui.playlist_panel import PlaylistPanel
from sara.ui.folder_playlist_panel import FolderPlaylistPanel
from sara.ui.news_playlist_panel import NewsPlaylistPanel
from sara.ui.playlist_layout import PlaylistLayoutManager, PlaylistLayoutState
from sara.ui.announcement_service import AnnouncementService
from sara.ui.playlist_devices_dialog import PlaylistDevicesDialog
from sara.ui.mix_point_dialog import MixPointEditorDialog
from sara.ui.options_dialog import OptionsDialog
from sara.ui.shortcut_editor_dialog import ShortcutEditorDialog
from sara.ui.shortcut_utils import format_shortcut_display, parse_shortcut
from sara.ui.nvda_sleep import notify_nvda_play_next
from sara.ui.file_selection_dialog import FileSelectionDialog
from sara.ui.playback_controller import PlaybackContext, PlaybackController
from sara.ui.auto_mix_tracker import AutoMixTracker
from sara.ui.clipboard_service import PlaylistClipboard


logger = logging.getLogger(__name__)


FADE_DURATION_SECONDS = 2.0
MIX_NATIVE_EARLY_GUARD = 0.25
MIX_NATIVE_LATE_GUARD = 0.35
MIX_EXPLICIT_PROGRESS_GUARD = 0.05
ANNOUNCEMENT_PREFIX = "\uf8ff"


@dataclass
class MixPlan:
    mix_at: float | None
    fade_seconds: float
    base_cue: float
    effective_duration: float
    native_trigger: bool
    triggered: bool = False


class MainFrame(wx.Frame):
    """Main window managing playlists and global shortcuts."""

    TITLE = "SARA"

    def __init__(
        self,
        parent: wx.Window | None = None,
        *,
        state: AppState | None = None,
        settings: SettingsManager | None = None,
        **kwargs,
    ) -> None:
        super().__init__(parent=parent, id=wx.ID_ANY, title=self.TITLE, size=(1200, 800), **kwargs)
        self.SetName("sara_main_frame")
        self._settings = settings or SettingsManager()
        set_language(self._settings.get_language())
        if not self._settings.config_path.exists():
            self._settings.save()
        self._playlists: Dict[str, PlaylistPanel] = {}
        self._playlist_wrappers: Dict[str, wx.Window] = {}
        self._playlist_headers: Dict[str, wx.StaticText] = {}
        self._playlist_titles: Dict[str, str] = {}
        self._layout = PlaylistLayoutManager()
        self._current_index: int = 0
        self._state = state or AppState()
        self._playlist_factory = PlaylistFactory()
        self._audio_engine = AudioEngine()
        self._playback = PlaybackController(self._audio_engine, self._settings, self._announce_event)
        self._play_next_id = wx.NewIdRef()
        self._add_tracks_id = wx.NewIdRef()
        self._assign_device_id = wx.NewIdRef()
        self._auto_mix_toggle_id = wx.NewIdRef()
        self._loop_playback_toggle_id = wx.NewIdRef()
        self._loop_info_id = wx.NewIdRef()
        self._track_remaining_id = wx.NewIdRef()
        self._remove_playlist_id = wx.NewIdRef()
        self._manage_playlists_id = wx.NewIdRef()
        self._cut_id = wx.NewIdRef()
        self._copy_id = wx.NewIdRef()
        self._paste_id = wx.NewIdRef()
        self._delete_id = wx.NewIdRef()
        self._move_up_id = wx.NewIdRef()
        self._move_down_id = wx.NewIdRef()
        self._undo_id = wx.NewIdRef()
        self._redo_id = wx.NewIdRef()
        self._shortcut_editor_id = wx.NewIdRef()
        self._playlist_hotkey_defaults = self._settings.get_playlist_shortcuts()
        self._playlist_action_ids: Dict[str, int] = {}
        self._action_by_id: Dict[int, str] = {}
        self._shortcut_menu_items: Dict[tuple[str, str], tuple[wx.MenuItem, str]] = {}
        self._auto_mix_enabled: bool = False
        self._alternate_play_next: bool = self._settings.get_alternate_play_next()
        self._swap_play_select: bool = self._settings.get_swap_play_select()
        self._auto_remove_played: bool = self._settings.get_auto_remove_played()
        self._focus_playing_track: bool = self._settings.get_focus_playing_track()
        self._intro_alert_seconds: float = self._settings.get_intro_alert_seconds()
        self._track_end_alert_seconds: float = self._settings.get_track_end_alert_seconds()
        self._clipboard = PlaylistClipboard()
        self._undo_manager = UndoManager(self._apply_undo_callback)
        self._focus_lock: Dict[str, bool] = self._layout.state.focus_lock
        self._intro_alert_players: list[Tuple[Player, Path]] = []
        self._track_end_alert_players: list[Tuple[Player, Path]] = []
        self._last_started_item_id: Dict[str, str | None] = {}
        self._last_music_playlist_id: str | None = None
        self._active_folder_preview: tuple[str, str] | None = None
        self._active_break_item: Dict[str, str] = {}  # playlist_id -> item_id z aktywnym breakiem
        self._mix_trigger_points: Dict[tuple[str, str], float] = {}  # (playlist_id, item_id) -> absolute mix_at seconds
        self._mix_plans: Dict[tuple[str, str], MixPlan] = {}
        self._auto_mix_tracker = AutoMixTracker()  # wirtualny kursor automix niezależny od UI
        self._auto_mix_busy: Dict[str, bool] = {}  # blokada reentrancji per playlist
        self._last_focus_index: Dict[str, int] = {}

        self._ensure_legacy_hooks()

        self.CreateStatusBar()
        self.SetStatusText(_("Ready"))
        self._announcer = AnnouncementService(self._settings, status_callback=self.SetStatusText)
        wx.ToolTip.Enable(False)
        self.SetToolTip(None)
        self._fade_duration = max(self._settings.get_playback_fade_seconds(), 0.0)
        self._create_menu_bar()
        self._create_ui()
        self._register_accessibility()
        self._configure_accelerators()
        self._global_shortcut_blocked = False

    def _ensure_legacy_hooks(self) -> None:
        if not hasattr(self, "_on_new_playlist"):
            self._on_new_playlist = self._create_playlist_dialog  # type: ignore[attr-defined]

    def _auto_mix_start_index(
        self,
        panel: PlaylistPanel,
        idx: int,
        *,
        restart_playing: bool = False,
        overlap_trigger: bool = False,
    ) -> bool:
        """Sekwencyjny start utworu o podanym indeksie w automixie (bez patrzenia na fokus/selection)."""
        playlist = panel.model
        total = len(playlist.items)
        if total == 0:
            return False
        idx = idx % total

        # zatrzymaj bieżący odtwarzacz (jeśli jest) i oznacz PLAYED, chyba że overlap_trigger
        current_ctx = self._get_playback_context(playlist.id)
        if current_ctx and not overlap_trigger:
            key, _ctx = current_ctx
            playing_item = playlist.get_item(key[1])
            if playing_item:
                playing_item.is_selected = False
                playing_item.status = PlaylistItemStatus.PLAYED
                playing_item.current_position = playing_item.effective_duration_seconds
            self._stop_playlist_playback(
                playlist.id,
                mark_played=True,
                fade_duration=max(0.0, self._fade_duration),
            )

        next_item = playlist.items[idx]
        next_item.is_selected = False
        next_item.status = PlaylistItemStatus.PENDING
        next_item.current_position = 0.0

        logger.debug(
            "UI: automix direct start idx=%s id=%s total=%s",
            idx,
            getattr(next_item, "id", None),
            total,
        )

        # restart_playing=True pozwala ominąć blokadę „PLAYED” w automixie
        started = self._start_playback(
            panel,
            next_item,
            restart_playing=True,
            auto_mix_sequence=True,
            prefer_overlap=overlap_trigger,
        )
        if started:
            self._last_started_item_id[playlist.id] = next_item.id
            self._auto_mix_tracker.set_last_started(playlist.id, next_item.id)
        return started

    def _create_menu_bar(self) -> None:
        menu_bar = wx.MenuBar()

        self._shortcut_menu_items.clear()

        playlist_menu = wx.Menu()
        new_item = playlist_menu.Append(wx.ID_NEW, _("&New playlist"))
        self._register_menu_shortcut(new_item, _("&New playlist"), "playlist_menu", "new")
        add_tracks_item = playlist_menu.Append(int(self._add_tracks_id), _("Add &tracks…"))
        self._register_menu_shortcut(add_tracks_item, _("Add &tracks…"), "playlist_menu", "add_tracks")
        assign_device_item = playlist_menu.Append(int(self._assign_device_id), _("Assign &audio device…"))
        self._register_menu_shortcut(assign_device_item, _("Assign &audio device…"), "playlist_menu", "assign_device")
        import_item = playlist_menu.Append(wx.ID_OPEN, _("&Import playlist"))
        self._register_menu_shortcut(import_item, _("&Import playlist"), "playlist_menu", "import")
        playlist_menu.AppendSeparator()
        remove_item = playlist_menu.Append(int(self._remove_playlist_id), _("&Remove playlist"))
        manage_item = playlist_menu.Append(int(self._manage_playlists_id), _("Manage &playlists…"))
        self._register_menu_shortcut(remove_item, _("&Remove playlist"), "playlist_menu", "remove")
        self._register_menu_shortcut(manage_item, _("Manage &playlists…"), "playlist_menu", "manage")
        playlist_menu.AppendSeparator()
        export_item = playlist_menu.Append(wx.ID_SAVE, _("&Export playlist…"))
        self._register_menu_shortcut(export_item, _("&Export playlist…"), "playlist_menu", "export")
        exit_item = playlist_menu.Append(wx.ID_EXIT, _("E&xit"))
        self._register_menu_shortcut(exit_item, _("E&xit"), "playlist_menu", "exit")
        menu_bar.Append(playlist_menu, _("&Playlist"))

        edit_menu = wx.Menu()
        self._append_shortcut_menu_item(edit_menu, self._undo_id, _("&Undo"), "edit", "undo")
        self._append_shortcut_menu_item(edit_menu, self._redo_id, _("Re&do"), "edit", "redo")
        edit_menu.AppendSeparator()
        self._append_shortcut_menu_item(edit_menu, self._cut_id, _("Cu&t"), "edit", "cut")
        self._append_shortcut_menu_item(edit_menu, self._copy_id, _("&Copy"), "edit", "copy")
        self._append_shortcut_menu_item(edit_menu, self._paste_id, _("&Paste"), "edit", "paste")
        edit_menu.AppendSeparator()
        self._append_shortcut_menu_item(edit_menu, self._delete_id, _("&Delete"), "edit", "delete")
        edit_menu.AppendSeparator()
        self._append_shortcut_menu_item(edit_menu, self._move_up_id, _("Move &up"), "edit", "move_up")
        self._append_shortcut_menu_item(edit_menu, self._move_down_id, _("Move &down"), "edit", "move_down")
        menu_bar.Append(edit_menu, _("&Edit"))

        tools_menu = wx.Menu()
        options_id = wx.NewIdRef()
        self._append_shortcut_menu_item(
            tools_menu,
            self._loop_playback_toggle_id,
            _("Toggle track &loop"),
            "global",
            "loop_playback_toggle",
        )

        self._append_shortcut_menu_item(
            tools_menu,
            self._loop_info_id,
            _("Loop &information"),
            "global",
            "loop_info",
        )
        self._append_shortcut_menu_item(
            tools_menu,
            self._track_remaining_id,
            _("Track &remaining time"),
            "global",
            "track_remaining",
        )

        tools_menu.Append(int(self._shortcut_editor_id), _("Edit &shortcuts…"))
        tools_menu.Append(int(options_id), _("&Options…"))
        menu_bar.Append(tools_menu, _("&Tools"))

        self.SetMenuBar(menu_bar)

        self.Bind(wx.EVT_MENU, self._on_new_playlist, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self._on_add_tracks, id=self._add_tracks_id)
        self.Bind(wx.EVT_MENU, self._on_assign_device, id=self._assign_device_id)
        self.Bind(wx.EVT_MENU, self._on_import_playlist, id=wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self._on_export_playlist, id=wx.ID_SAVE)
        self.Bind(wx.EVT_MENU, self._on_exit, id=wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, self._on_remove_playlist, id=self._remove_playlist_id)
        self.Bind(wx.EVT_MENU, self._on_manage_playlists, id=self._manage_playlists_id)
        self.Bind(wx.EVT_MENU, self._on_options, id=int(options_id))
        self.Bind(wx.EVT_MENU, self._on_toggle_loop_playback, id=int(self._loop_playback_toggle_id))
        self.Bind(wx.EVT_MENU, self._on_loop_info, id=int(self._loop_info_id))
        self.Bind(wx.EVT_MENU, self._on_track_remaining, id=int(self._track_remaining_id))
        self.Bind(wx.EVT_MENU, self._on_edit_shortcuts, id=int(self._shortcut_editor_id))
        self.Bind(wx.EVT_MENU, self._on_undo, id=int(self._undo_id))
        self.Bind(wx.EVT_MENU, self._on_redo, id=int(self._redo_id))
        self.Bind(wx.EVT_MENU, self._on_cut_selection, id=int(self._cut_id))
        self.Bind(wx.EVT_MENU, self._on_copy_selection, id=int(self._copy_id))
        self.Bind(wx.EVT_MENU, self._on_paste_selection, id=int(self._paste_id))
        self.Bind(wx.EVT_MENU, self._on_delete_selection, id=int(self._delete_id))
        self.Bind(wx.EVT_MENU, self._on_move_selection_up, id=int(self._move_up_id))
        self.Bind(wx.EVT_MENU, self._on_move_selection_down, id=int(self._move_down_id))
        self.Bind(wx.EVT_CHAR_HOOK, self._handle_global_char_hook)

    def _append_shortcut_menu_item(
        self,
        menu: wx.Menu,
        command_id: wx.WindowIDRef | int,
        base_label: str,
        scope: str,
        action: str,
        *,
        check: bool = False,
    ) -> wx.MenuItem:
        item_id = int(command_id)
        menu_item = menu.AppendCheckItem(item_id, base_label) if check else menu.Append(item_id, base_label)
        self._register_menu_shortcut(menu_item, base_label, scope, action)
        return menu_item

    def _register_menu_shortcut(self, menu_item: wx.MenuItem, base_label: str, scope: str, action: str) -> None:
        if get_shortcut(scope, action) is None:
            raise ValueError(f"Shortcut not registered for action {scope}:{action}")
        self._shortcut_menu_items[(scope, action)] = (menu_item, base_label)
        self._apply_shortcut_to_menu_item(scope, action)

    def _apply_shortcut_to_menu_item(self, scope: str, action: str) -> None:
        entry = self._shortcut_menu_items.get((scope, action))
        if not entry:
            return
        menu_item, base_label = entry
        shortcut_value = self._settings.get_shortcut(scope, action)
        shortcut_label = format_shortcut_display(shortcut_value)
        label = base_label if not shortcut_label else f"{base_label}\t{shortcut_label}"
        menu_item.SetItemLabel(label)

    def _update_shortcut_menu_labels(self) -> None:
        for scope, action in self._shortcut_menu_items.keys():
            self._apply_shortcut_to_menu_item(scope, action)

    def _refresh_playlist_hotkeys(self) -> None:
        for panel in self._playlists.values():
            model = panel.model
            for action, shortcut in self._playlist_hotkey_defaults.items():
                descriptor = get_shortcut("playlist", action)
                description = descriptor.label if descriptor else action.title()
                model.hotkeys[action] = HotkeyAction(key=shortcut, description=description)

    def _apply_swap_play_select_option(self) -> None:
        for panel in self._playlists.values():
            if isinstance(panel, PlaylistPanel) and panel.model.kind is PlaylistKind.MUSIC:
                panel.set_swap_play_select(self._swap_play_select)

    def _create_ui(self) -> None:
        panel = wx.Panel(self)
        self._sizer = wx.BoxSizer(wx.VERTICAL)
        panel.SetSizer(self._sizer)

        self._playlist_container = wx.ScrolledWindow(panel, style=wx.HSCROLL | wx.VSCROLL)
        self._playlist_container.SetScrollRate(10, 10)
        self._playlist_sizer = wx.WrapSizer(wx.HORIZONTAL)
        self._playlist_container.SetSizer(self._playlist_sizer)
        self._sizer.Add(self._playlist_container, 1, wx.EXPAND | wx.ALL, 10)

        existing_playlists = list(self._state.iter_playlists())
        if not existing_playlists:
            existing_playlists = self._populate_startup_playlists()
            if not existing_playlists:
                shortcut_label = format_shortcut_display(self._settings.get_shortcut("playlist_menu", "new"))
                if not shortcut_label:
                    descriptor = get_shortcut("playlist_menu", "new")
                    if descriptor:
                        shortcut_label = format_shortcut_display(descriptor.default)
                if shortcut_label:
                    self._announce_event(
                        "playlist",
                        _("No playlists available. Use %s to add a new playlist.") % shortcut_label,
                    )
                else:
                    self._announce_event(
                        "playlist",
                        _("No playlists available. Use the Playlist menu to add one."),
                    )
        for playlist in existing_playlists:
            self.add_playlist(playlist)
        if self._layout.state.order:
            wx.CallAfter(self._focus_playlist_panel, self._layout.state.order[0])

    def _register_accessibility(self) -> None:
        # Placeholder: konfiguracje wx.Accessible zostaną dodane w przyszłych iteracjach
        pass

    def _populate_startup_playlists(self) -> list[PlaylistModel]:
        created: list[PlaylistModel] = []
        for entry in self._settings.get_startup_playlists():
            name = entry.get("name")
            if not name:
                continue
            existing = next((pl for pl in self._state.iter_playlists() if pl.name == name), None)
            if existing:
                created.append(existing)
                continue
            kind = entry.get("kind", PlaylistKind.MUSIC)
            if not isinstance(kind, PlaylistKind):
                try:
                    kind = PlaylistKind(kind)
                except Exception:
                    kind = PlaylistKind.MUSIC
            folder_path = entry.get("folder_path")
            if folder_path and not isinstance(folder_path, Path):
                folder_path = Path(folder_path)
            model = self._playlist_factory.create_playlist(name, kind=kind, folder_path=folder_path)
            slots = entry.get("slots", [])
            if isinstance(slots, list) and kind is not PlaylistKind.FOLDER:
                model.set_output_slots(slots)
            created.append(model)
        return created

    def _configure_accelerators(self) -> None:
        accel_entries: list[tuple[int, int, int]] = []
        self._playlist_hotkey_defaults = self._settings.get_playlist_shortcuts()
        self._playlist_action_ids.clear()
        self._action_by_id.clear()

        def add_entry(scope: str, action: str, command_id: int) -> None:
            shortcut_value = self._settings.get_shortcut(scope, action)
            modifiers_key = parse_shortcut(shortcut_value)
            if not modifiers_key:
                descriptor = get_shortcut(scope, action)
                if descriptor:
                    modifiers_key = parse_shortcut(descriptor.default)
            if not modifiers_key:
                return
            modifiers, keycode = modifiers_key
            accel_entries.append((modifiers, keycode, command_id))
            if keycode == wx.WXK_RETURN:
                accel_entries.append((modifiers, wx.WXK_NUMPAD_ENTER, command_id))

        play_next_id = int(self._play_next_id)
        add_entry("global", "play_next", play_next_id)
        self.Bind(wx.EVT_MENU, self._on_global_play_next, id=play_next_id)

        auto_mix_id = int(self._auto_mix_toggle_id)
        add_entry("global", "auto_mix_toggle", auto_mix_id)
        self.Bind(wx.EVT_MENU, self._on_toggle_auto_mix, id=auto_mix_id)

        add_entry("global", "loop_playback_toggle", int(self._loop_playback_toggle_id))
        add_entry("global", "loop_info", int(self._loop_info_id))
        add_entry("global", "track_remaining", int(self._track_remaining_id))

        add_entry("playlist_menu", "new", wx.ID_NEW)
        add_entry("playlist_menu", "add_tracks", int(self._add_tracks_id))
        add_entry("playlist_menu", "assign_device", int(self._assign_device_id))
        add_entry("playlist_menu", "import", wx.ID_OPEN)
        add_entry("playlist_menu", "remove", int(self._remove_playlist_id))
        add_entry("playlist_menu", "manage", int(self._manage_playlists_id))
        add_entry("playlist_menu", "exit", wx.ID_EXIT)

        add_entry("edit", "undo", int(self._undo_id))
        add_entry("edit", "redo", int(self._redo_id))
        add_entry("edit", "cut", int(self._cut_id))
        add_entry("edit", "copy", int(self._copy_id))
        add_entry("edit", "paste", int(self._paste_id))
        add_entry("edit", "delete", int(self._delete_id))
        add_entry("edit", "move_up", int(self._move_up_id))
        add_entry("edit", "move_down", int(self._move_down_id))

        for action, key in self._playlist_hotkey_defaults.items():
            parsed_action = parse_shortcut(key)
            if not parsed_action:
                descriptor = get_shortcut("playlist", action)
                if descriptor:
                    parsed_action = parse_shortcut(descriptor.default)
            if not parsed_action:
                continue
            modifiers, keycode = parsed_action
            cmd_id_ref = wx.NewIdRef()
            cmd_id = int(cmd_id_ref)
            self._playlist_action_ids[action] = cmd_id
            self._action_by_id[cmd_id] = action
            accel_entries.append((modifiers, keycode, cmd_id))
            if keycode == wx.WXK_RETURN:
                accel_entries.append((modifiers, wx.WXK_NUMPAD_ENTER, cmd_id))
            self.Bind(wx.EVT_MENU, self._on_playlist_hotkey, id=cmd_id)

        accel_table = wx.AcceleratorTable(accel_entries)
        self.SetAcceleratorTable(accel_table)

    def _handle_global_char_hook(self, event: wx.KeyEvent) -> None:
        keycode = event.GetKeyCode()
        if self._should_handle_altgr_track_remaining(event, keycode):
            self._on_track_remaining()
            return
        if keycode == wx.WXK_F6:
            if self._cycle_playlist_focus(backwards=event.ShiftDown()):
                return
        panel, focus = self._active_news_panel()
        if keycode == wx.WXK_SPACE and panel and panel.is_edit_control(focus):
            event.Skip()
            event.StopPropagation()
            return
        event.Skip()

    def _should_handle_altgr_track_remaining(self, event: wx.KeyEvent, keycode: int) -> bool:
        if keycode not in (ord("T"), ord("t")):
            return False
        modifiers = event.GetModifiers()
        altgr_flag = getattr(wx, "MOD_ALTGR", None)
        if isinstance(modifiers, int) and altgr_flag and modifiers & altgr_flag:
            return True
        if event.AltDown() and event.ControlDown() and not event.MetaDown():
            return True
        return False

    def add_playlist(self, model: PlaylistModel) -> None:
        for action, key in self._playlist_hotkey_defaults.items():
            model.hotkeys.setdefault(action, HotkeyAction(key=key, description=action.title()))

        saved_slots = self._settings.get_playlist_outputs(model.name)
        if saved_slots:
            model.set_output_slots(saved_slots)

        container = wx.Panel(self._playlist_container, style=wx.TAB_TRAVERSAL)
        container.SetName(model.name)

        header = wx.StaticText(container, label=model.name)
        header_font = header.GetFont()
        header_font.MakeBold()
        header.SetFont(header_font)
        header.SetName(model.name)
        header.Bind(wx.EVT_LEFT_DOWN, lambda event, playlist_id=model.id: self._handle_focus_click(event, playlist_id))

        if model.kind is PlaylistKind.NEWS:
            panel = NewsPlaylistPanel(
                container,
                model=model,
                get_line_length=self._settings.get_news_line_length,
                get_audio_devices=self._news_device_entries,
                on_focus=self._on_playlist_focus,
                on_play_audio=lambda path, device: self._play_news_audio_clip(model, path, device),
                on_device_change=lambda _model=model: self._persist_playlist_outputs(model),
                on_preview_audio=self._preview_news_clip,
                on_stop_preview_audio=self._stop_preview,
            )
        elif model.kind is PlaylistKind.FOLDER:
            panel = FolderPlaylistPanel(
                container,
                model=model,
                on_focus=self._on_playlist_focus,
                on_selection_change=self._on_playlist_selection_change,
                on_mix_configure=self._on_mix_points_configure,
                on_preview_request=lambda playlist_id, item_id: self._handle_folder_preview(
                    playlist_id, item_id
                ),
                on_send_to_music=lambda playlist_id, item_ids: self._send_folder_items_to_music(
                    playlist_id, item_ids
                ),
                on_select_folder=lambda playlist_id: self._select_folder_for_playlist(playlist_id),
                on_reload_folder=lambda playlist_id: self._reload_folder_playlist(playlist_id),
            )
        else:
            panel = PlaylistPanel(
                container,
                model=model,
                on_focus=self._on_playlist_focus,
                on_mix_configure=self._on_mix_points_configure,
                on_toggle_selection=self._on_toggle_selection,
                on_selection_change=self._on_playlist_selection_change,
                on_play_request=self._on_playlist_play_request,
                swap_play_select=self._swap_play_select,
            )
        panel.SetMinSize((360, 300))

        column_sizer = wx.BoxSizer(wx.VERTICAL)
        column_sizer.Add(header, 0, wx.ALL | wx.EXPAND, 5)
        column_sizer.Add(wx.StaticLine(container), 0, wx.LEFT | wx.RIGHT, 5)
        column_sizer.Add(panel, 1, wx.EXPAND | wx.ALL, 5)
        container.SetSizer(column_sizer)
        container.SetMinSize((380, 320))

        container.Bind(wx.EVT_LEFT_DOWN, lambda event, playlist_id=model.id: self._handle_focus_click(event, playlist_id))

        self._playlist_sizer.Add(container, 0, wx.EXPAND | wx.ALL, 8)
        self._playlist_container.Layout()
        self._playlist_container.FitInside()

        self._playlists[model.id] = panel
        self._playlist_wrappers[model.id] = container
        self._playlist_headers[model.id] = header
        self._playlist_titles[model.id] = model.name
        self._last_started_item_id.setdefault(model.id, None)
        if model.kind is PlaylistKind.FOLDER and model.folder_path:
            self._load_folder_playlist(model, announce=False)
        self._layout.add_playlist(model.id)
        if model.id not in self._state.playlists:
            self._state.add_playlist(model)
        self._update_active_playlist_styles()
        self._announce_event("playlist", _("Playlist %s added") % model.name)

    def _get_playlist_model(self, playlist_id: str) -> PlaylistModel | None:
        return self._state.playlists.get(playlist_id)

    def _playlist_has_selection(self, playlist_id: str) -> bool:
        model = self._get_playlist_model(playlist_id)
        if not model:
            return False
        return any(item.is_selected for item in model.items)

    def _apply_playlist_order(self, order: list[str]) -> None:
        applied = self._layout.apply_order(order)
        self._playlist_sizer.Clear(delete_windows=False)
        for playlist_id in self._layout.state.order:
            wrapper = self._playlist_wrappers.get(playlist_id)
            if wrapper is not None:
                self._playlist_sizer.Add(wrapper, 0, wx.EXPAND | wx.ALL, 8)
        self._playlist_container.Layout()
        self._playlist_container.FitInside()
        self._current_index = self._layout.current_index()
        self._update_active_playlist_styles()

    def _remove_playlist_by_id(self, playlist_id: str, *, announce: bool = True) -> bool:
        panel = self._playlists.get(playlist_id)
        if panel is None:
            return False
        self._stop_playlist_playback(playlist_id, mark_played=False, fade_duration=0.0)
        self._playlists.pop(playlist_id, None)
        title = self._playlist_titles.pop(playlist_id, playlist_id)
        wrapper = self._playlist_wrappers.pop(playlist_id, None)
        if wrapper is not None:
            wrapper.Destroy()
        header = self._playlist_headers.pop(playlist_id, None)
        if header is not None:
            header.Destroy()
        self._state.remove_playlist(playlist_id)
        self._focus_lock.pop(playlist_id, None)
        self._layout.remove_playlist(playlist_id)
        self._playlist_titles.pop(playlist_id, None)
        self._playlist_container.Layout()
        self._playlist_container.FitInside()
        self._playback.clear_playlist_entries(playlist_id)
        self._last_started_item_id.pop(playlist_id, None)
        if self._active_folder_preview and self._active_folder_preview[0] == playlist_id:
            self._stop_preview()
        if self._last_music_playlist_id == playlist_id:
            self._last_music_playlist_id = None
        self._apply_playlist_order(self._layout.state.order)
        if announce:
            self._announce_event("playlist", _("Removed playlist %s") % title)
        return True
    @staticmethod
    def _format_track_name(item: PlaylistItem) -> str:
        return f"{item.artist} - {item.title}" if item.artist else item.title

    def _news_device_entries(self) -> list[tuple[str, str]]:
        entries: list[tuple[str, str]] = [(None, _("(use global/PFL device)"))]
        entries.extend((device.id, device.name) for device in self._audio_engine.get_devices())
        return entries

    def _play_news_audio_clip(self, model: PlaylistModel, clip_path: Path, device_id: str | None) -> None:
        if not clip_path.exists():
            self._announce_event("device", _("Audio file %s does not exist") % clip_path)
            return
        configured = model.get_configured_slots()
        target_device = device_id or (configured[0] if configured else None) or self._settings.get_pfl_device()
        if not target_device:
            self._announce_event("device", _("Select a playback device first"))
            return
        try:
            player = self._audio_engine.create_player(target_device)
        except ValueError:
            self._announce_event("device", _("Device %s is not available") % target_device)
            return
        try:
            player.play(f"{model.id}:news", str(clip_path))
        except Exception as exc:  # pylint: disable=broad-except
            self._announce_event("device", _("Failed to play audio clip: %s") % exc)

    def _preview_news_clip(self, clip_path: Path) -> bool:
        if not clip_path.exists():
            self._announce_event("pfl", _("Audio file %s does not exist") % clip_path)
            return False
        temp_item = PlaylistItem(
            id=f"news-preview-{clip_path.stem}",
            path=clip_path,
            title=clip_path.name,
            duration_seconds=0.0,
        )
        return self._playback.start_preview(temp_item, 0.0)

    def _persist_playlist_outputs(self, model: PlaylistModel) -> None:
        self._settings.set_playlist_outputs(model.name, model.get_configured_slots())
        self._settings.save()

    def _select_folder_for_playlist(self, playlist_id: str) -> None:
        panel = self._playlists.get(playlist_id)
        if not isinstance(panel, FolderPlaylistPanel):
            return
        dialog = FileSelectionDialog(
            self,
            title=_("Select folder"),
            allow_directories=True,
            directories_only=True,
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            paths = dialog.get_paths()
        finally:
            dialog.Destroy()
        if not paths:
            return
        selected = Path(paths[0])
        if not selected.exists() or not selected.is_dir():
            self._announce_event("playlist", _("Folder %s does not exist") % selected)
            return
        panel.model.folder_path = selected
        panel.set_folder_path(selected)
        self._load_folder_playlist(panel.model)

    def _reload_folder_playlist(self, playlist_id: str) -> None:
        panel = self._playlists.get(playlist_id)
        if not isinstance(panel, FolderPlaylistPanel):
            return
        folder_path = panel.model.folder_path
        if not folder_path:
            self._announce_event("playlist", _("Select a folder first"))
            return
        self._load_folder_playlist(panel.model)

    def _load_folder_playlist(self, playlist: PlaylistModel, *, announce: bool = True) -> None:
        folder_path = playlist.folder_path
        if not folder_path:
            self._announce_event("playlist", _("Select a folder first"))
            return
        if not folder_path.exists():
            self._announce_event("playlist", _("Folder %s does not exist") % folder_path)
            return
        description = _("Loading folder %s…") % folder_path.name
        self._run_item_loader(
            description=description,
            worker=lambda folder=folder_path: self._load_folder_items(folder),
            on_complete=lambda result, playlist_id=playlist.id, folder=folder_path: self._finalize_folder_load(
                playlist_id, folder, result, announce=announce
            ),
        )

    def _load_folder_items(self, folder_path: Path) -> tuple[list[PlaylistItem], int]:
        file_paths, skipped = self._collect_files_from_paths([folder_path])
        items = self._create_items_from_paths(file_paths)
        return items, skipped

    def _finalize_folder_load(
        self,
        playlist_id: str,
        folder_path: Path,
        result: tuple[list[PlaylistItem], int] | list[PlaylistItem],
        *,
        announce: bool,
    ) -> None:
        panel = self._playlists.get(playlist_id)
        if not isinstance(panel, FolderPlaylistPanel):
            return
        if playlist_id not in self._playlists or panel.model is None:
            return
        if isinstance(result, tuple):
            items, skipped = result
        else:
            items, skipped = result, 0
        panel.model.items = items
        panel.model.folder_path = folder_path
        panel.set_folder_path(folder_path)
        panel.refresh(selected_indices=None, focus=False)
        if announce:
            self._announce_event(
                "playlist",
                _("Loaded %d tracks from %s") % (len(items), folder_path.name),
            )
        if skipped:
            noun = _("file") if skipped == 1 else _("files")
            self._announce_event("playlist", _("Skipped %d unsupported %s") % (skipped, noun))

    def _handle_folder_preview(self, playlist_id: str, item_id: str) -> None:
        panel = self._playlists.get(playlist_id)
        if not isinstance(panel, FolderPlaylistPanel):
            return
        item = panel.model.get_item(item_id)
        if not item:
            return
        if self._active_folder_preview == (playlist_id, item_id):
            if self._playback.preview_context:
                self._stop_preview()
            else:
                self._active_folder_preview = None
            return
        if self._playback.start_preview(item, 0.0):
            self._active_folder_preview = (playlist_id, item_id)

    def _stop_preview(self) -> None:
        try:
            self._playback.stop_preview()
        finally:
            self._active_folder_preview = None

    def _send_folder_items_to_music(self, playlist_id: str, item_ids: Sequence[str]) -> None:
        panel = self._playlists.get(playlist_id)
        if not isinstance(panel, FolderPlaylistPanel):
            return
        target = self._target_music_playlist()
        if not target:
            self._announce_event("playlist", _("Add a music playlist first"))
            return
        target_panel, target_model = target
        source_items = [
            panel.model.get_item(item_id)
            for item_id in item_ids
        ]
        source_items = [item for item in source_items if item]
        if not source_items:
            self._announce_event("playlist", _("No tracks selected"))
            return
        serialized = self._serialize_items(source_items)
        new_items = [self._create_item_from_serialized(data) for data in serialized]
        selected_indices = target_panel.get_selected_indices()
        anchor = selected_indices[-1] if selected_indices else None
        insert_at = anchor + 1 if anchor is not None else len(target_model.items)
        target_model.items[insert_at:insert_at] = new_items
        insert_indices = list(range(insert_at, insert_at + len(new_items)))
        target_panel.refresh(insert_indices, focus=False)
        self._announce_event(
            "playlist",
            _("Added %d tracks to playlist %s") % (len(new_items), target_model.name),
        )
        operation = InsertOperation(indices=list(insert_indices), items=list(new_items))
        self._push_undo_action(target_model, operation)

    def _target_music_playlist(self) -> tuple[PlaylistPanel, PlaylistModel] | None:
        candidate_ids: list[str] = []
        if self._last_music_playlist_id:
            candidate_ids.append(self._last_music_playlist_id)
        for playlist_id in self._layout.state.order:
            if playlist_id not in candidate_ids:
                candidate_ids.append(playlist_id)
        for playlist_id in candidate_ids:
            panel = self._playlists.get(playlist_id)
            if isinstance(panel, PlaylistPanel) and panel.model.kind is PlaylistKind.MUSIC:
                self._last_music_playlist_id = playlist_id
                return panel, panel.model
        return None
    def _refresh_news_panels(self) -> None:
        for panel in self._playlists.values():
            if isinstance(panel, NewsPlaylistPanel):
                panel.refresh_configuration()
    def _active_news_panel(self) -> tuple[NewsPlaylistPanel | None, wx.Window | None]:
        focus = wx.Window.FindFocus()
        if focus is None:
            return None, None
        for panel in self._playlists.values():
            if isinstance(panel, NewsPlaylistPanel) and panel.contains_window(focus):
                return panel, focus
        return None, focus

    def _focused_playlist_id(self) -> str | None:
        focus = wx.Window.FindFocus()
        if focus is None:
            return None
        for playlist_id, wrapper in self._playlist_wrappers.items():
            current = focus
            while current:
                if current is wrapper:
                    return playlist_id
                current = current.GetParent()
        return None

    def _focus_playlist_panel(self, playlist_id: str) -> bool:
        panel = self._playlists.get(playlist_id)
        if panel is None:
            return False
        if isinstance(panel, NewsPlaylistPanel):
            panel.focus_default()
        elif isinstance(panel, PlaylistPanel):
            panel.focus_list()
        else:
            return False
        self._on_playlist_focus(playlist_id)
        return True

    def _cycle_playlist_focus(self, *, backwards: bool) -> bool:
        order = [playlist_id for playlist_id in self._layout.state.order if playlist_id in self._playlists]
        if not order:
            self._announce_event("playlist", _("No playlists available"))
            return False
        current_id = self._focused_playlist_id()
        if current_id in order:
            current_index = order.index(current_id)
            next_index = (current_index - 1) if backwards else (current_index + 1)
        else:
            next_index = len(order) - 1 if backwards else 0
        target_id = order[next_index % len(order)]
        return self._focus_playlist_panel(target_id)

    def _on_playlist_selection_change(self, playlist_id: str, indices: list[int]) -> None:
        panel = self._playlists.get(playlist_id)
        if not isinstance(panel, PlaylistPanel):
            return
        # pobierz aktualne zaznaczenia z kontrolki (lista zdarzenia bywa opóźniona)
        indices = panel.get_selected_indices()
        playing_id = self._get_playing_item_id(playlist_id)
        loop_active = False
        focus_idx = panel.get_focused_index()
        if focus_idx != wx.NOT_FOUND and 0 <= focus_idx < len(panel.model.items):
            sel_item = panel.model.items[focus_idx]
            loop_active = sel_item.has_loop() and (sel_item.loop_enabled or getattr(sel_item, "loop_auto_enabled", False))
        elif indices:
            idx0 = indices[0]
            if 0 <= idx0 < len(panel.model.items):
                sel_item = panel.model.items[idx0]
                loop_active = sel_item.has_loop() and (sel_item.loop_enabled or getattr(sel_item, "loop_auto_enabled", False))

        # focus-lock logika jak wcześniej
        if self._focus_playing_track:
            if playing_id is None or not indices:
                self._focus_lock[playlist_id] = False
            elif len(indices) == 1:
                selected_index = indices[0]
                if 0 <= selected_index < len(panel.model.items):
                    selected_item = panel.model.items[selected_index]
                    if selected_item.id == playing_id:
                        self._focus_lock[playlist_id] = False
                        # nie uciekaj wcześniej – pozwól ogłosić pętlę
                        if loop_active:
                            self._announce_event("selection", _("Loop enabled"))
                        return
                self._focus_lock[playlist_id] = True

        # komunikat o zaznaczeniu z informacją o pętli/auto-mix
        # komunikat o pętli przy pojedynczym zaznaczeniu
        if len(indices) == 1:
            idx = indices[0]
            if 0 <= idx < len(panel.model.items):
                item = panel.model.items[idx]
                focus_idx = panel.get_focused_index()
                if focus_idx != wx.NOT_FOUND:
                    self._last_focus_index[playlist_id] = focus_idx
                elif idx is not None:
                    self._last_focus_index[playlist_id] = idx
        # komunikat o pętli obsługuje teraz sam wiersz (prefiks „Loop” w tytule/statusie)

    def _on_playlist_play_request(self, playlist_id: str, item_id: str) -> None:
        self._play_item_direct(playlist_id, item_id)

    def _play_item_direct(self, playlist_id: str, item_id: str) -> bool:
        panel = self._playlists.get(playlist_id)
        playlist = self._get_playlist_model(playlist_id)
        if not isinstance(panel, PlaylistPanel) or playlist is None:
            return False
        if self._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC:
            return self._auto_mix_play_next(panel)
        item = playlist.get_item(item_id)
        if item is None:
            return False
        if self._start_playback(panel, item, restart_playing=True):
            self._last_started_item_id[playlist.id] = item.id
            status_message = _("Playing %s from playlist %s") % (self._format_track_name(item), playlist.name)
            self._announce_event("playback_events", status_message, spoken_message="")
            if self._swap_play_select and playlist.kind is PlaylistKind.MUSIC:
                playlist.clear_selection(item.id)
                self._refresh_selection_display(playlist.id)
            return True
        return False

    def _on_new_playlist(self, event: wx.CommandEvent) -> None:
        self._create_playlist_dialog(event)

    def _create_playlist_dialog(self, _event: wx.CommandEvent) -> None:
        self._prompt_new_playlist()

    def _prompt_new_playlist(self) -> PlaylistModel | None:
        dialog = NewPlaylistDialog(self)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return None
            model = self._playlist_factory.create_playlist(
                dialog.playlist_name,
                kind=dialog.playlist_kind,
                folder_path=dialog.folder_path if dialog.playlist_kind is PlaylistKind.FOLDER else None,
            )
            self.add_playlist(model)
            if dialog.playlist_kind is not PlaylistKind.FOLDER:
                self._configure_playlist_devices(model.id)
            return model
        finally:
            dialog.Destroy()

    def _on_add_tracks(self, event: wx.CommandEvent) -> None:
        panel = self._get_current_music_panel()
        if panel is None:
            self._announce_event("playlist", _("Select a playlist first"))
            return

        style = wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE
        wildcard = _("Audio files (*.mp3;*.mp2;*.wav;*.flac;*.ogg)|*.mp3;*.mp2;*.wav;*.flac;*.ogg|All files|*.*")
        dialog = FileSelectionDialog(
            self,
            title=_("Select audio files"),
            wildcard=wildcard,
            style=style,
        )
        result = dialog.ShowModal()
        paths = [Path(path) for path in dialog.get_paths()] if result == wx.ID_OK else []
        dialog.Destroy()
        if result != wx.ID_OK:
            return

        if not paths:
            self._announce_event("playlist", _("No tracks were added"))
            return

        description = _("Loading %d selected tracks…") % len(paths)
        self._run_item_loader(
            description=description,
            worker=lambda paths=paths: self._create_items_from_paths(paths),
            on_complete=lambda items, panel=panel: self._finalize_add_tracks(panel, items),
        )

    def _finalize_add_tracks(self, panel: PlaylistPanel, new_items: list[PlaylistItem]) -> None:
        playlist_id = panel.model.id
        if playlist_id not in self._playlists or self._playlists.get(playlist_id) is not panel:
            return
        if not new_items:
            self._announce_event("playlist", _("No tracks were added"))
            return
        panel.append_items(new_items)
        self._announce_event(
            "playlist",
            _("Added %d tracks to playlist %s") % (len(new_items), panel.model.name),
        )

    def _on_remove_playlist(self, _event: wx.CommandEvent) -> None:
        playlist_id = self._layout.state.current_id
        if not playlist_id:
            self._announce_event("playlist", _("No playlist selected"))
            return
        title = self._playlist_titles.get(playlist_id, _("playlist"))
        response = wx.MessageBox(
            _("Remove playlist %s?") % title,
            _("Confirm removal"),
            style=wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
            parent=self,
        )
        if response != wx.YES:
            return
        if not self._remove_playlist_by_id(playlist_id):
            self._announce_event("playlist", _("Unable to remove playlist"))

    def _on_manage_playlists(self, _event: wx.CommandEvent) -> None:
        entries: list[dict[str, Any]] = []
        for playlist_id in self._layout.state.order:
            panel = self._playlists.get(playlist_id)
            if not panel:
                continue
            name = self._playlist_titles.get(playlist_id, panel.model.name)
            entries.append(
                {
                    "id": playlist_id,
                    "name": name,
                    "kind": panel.model.kind,
                    "slots": list(panel.model.get_configured_slots()),
                }
            )
        if not entries:
            self._announce_event("playlist", _("No playlists available"))
            return
        dialog = ManagePlaylistsDialog(
            self,
            entries,
            create_callback=self._prompt_new_playlist,
            configure_callback=self._configure_playlist_devices,
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            result = dialog.get_result()
        finally:
            dialog.Destroy()
        if not result:
            return
        removed = result["removed"]
        for playlist_id in removed:
            self._remove_playlist_by_id(playlist_id, announce=False)
        self._apply_playlist_order(result["order"])
        if removed:
            self._announce_event("playlist", _("Removed %d playlists") % len(removed))

    def _on_assign_device(self, _event: wx.CommandEvent) -> None:
        panel = self._get_current_playlist_panel()
        if panel is None:
            self._announce_event("playlist", _("Select a playlist first"))
            return
        if isinstance(panel, PlaylistPanel) and panel.model.kind is PlaylistKind.FOLDER:
            self._announce_event("playlist", _("Music folders use the configured PFL device"))
            return
        self._configure_playlist_devices(panel.model.id)

    def _configure_playlist_devices(self, playlist_id: str) -> list[str | None] | None:
        panel = self._playlists.get(playlist_id)
        if panel is None:
            return None
        devices = self._audio_engine.get_devices()
        if not devices:
            self._announce_event("device", _("No audio devices available"))
            return None
        model = panel.model
        dialog = PlaylistDevicesDialog(self, devices=devices, slots=model.get_configured_slots())
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return None
            slots = dialog.get_slots()
        finally:
            dialog.Destroy()

        model.set_output_slots(slots)
        self._persist_playlist_outputs(model)

        device_map = {device.id: device for device in devices}
        assigned_names = [
            device_map[device_id].name
            for device_id in slots
            if device_id and device_id in device_map
        ]
        if assigned_names:
            self._announce_event(
                "playlist",
                _("Playlist %s assigned to players: %s") % (model.name, ", ".join(assigned_names)),
            )
        else:
            self._announce_event(
                "playlist",
                _("Removed device assignments for playlist %s") % model.name,
            )
        return slots

    def _on_import_playlist(self, event: wx.CommandEvent) -> None:
        panel = self._get_current_playlist_panel()
        if panel is None:
            self._announce_event("playlist", _("Select a playlist first"))
            return
        if isinstance(panel, NewsPlaylistPanel):
            result = panel.prompt_load_service()
            if result:
                self._announce_event(
                    "import_export",
                    _("Imported news service from %s") % result.name,
                )
            return
        if not isinstance(panel, PlaylistPanel):
            self._announce_event("playlist", _("Active playlist does not support import"))
            return
        if panel.model.kind is PlaylistKind.FOLDER:
            self._announce_event("playlist", _("Music folder playlists do not support import"))
            return

        dialog = FileSelectionDialog(
            self,
            title=_("Import playlist"),
            message=_("Select playlist"),
            wildcard=_("M3U playlists (*.m3u)|*.m3u|All files|*.*"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        result = dialog.ShowModal()
        selected_paths = dialog.get_paths() if result == wx.ID_OK else []
        dialog.Destroy()
        if result != wx.ID_OK or not selected_paths:
            return

        path = Path(selected_paths[0])

        try:
            entries = self._parse_m3u(path)
        except Exception as exc:  # pylint: disable=broad-except
            self._announce_event("import_export", _("Failed to import playlist: %s") % exc)
            return

        if not entries:
            self._announce_event("import_export", _("Playlist file is empty"))
            return

        description = _("Importing tracks from %s…") % path.name
        self._run_item_loader(
            description=description,
            worker=lambda entries=entries: self._create_items_from_m3u_entries(entries),
            on_complete=lambda items, panel=panel, filename=path.name: self._finalize_import_playlist(panel, items, filename),
        )

    def _parse_m3u(self, path: Path) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        current_title: str | None = None
        current_duration: float | None = None

        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception as exc:  # pylint: disable=broad-except
            raise RuntimeError(_("Failed to read playlist file: %s") % exc) from exc

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#EXTM3U"):
                continue
            if stripped.startswith("#EXTINF:"):
                try:
                    header, title = stripped.split(",", 1)
                except ValueError:
                    header, title = stripped, ""
                try:
                    duration = float(header[8:])
                except ValueError:
                    duration = None
                current_duration = duration if duration and duration >= 0 else None
                current_title = title.strip() if title.strip() else None
                continue

            entry_path = stripped
            entries.append(
                {
                    "path": entry_path,
                    "title": current_title,
                    "duration": current_duration,
                }
            )
            current_title = None
            current_duration = None

        return entries

    def _on_export_playlist(self, _event: wx.CommandEvent) -> None:
        panel = self._get_current_playlist_panel()
        if panel is None:
            self._announce_event("playlist", _("Select a playlist first"))
            return
        if isinstance(panel, NewsPlaylistPanel):
            result = panel.prompt_save_service()
            if result:
                self._announce_event(
                    "import_export",
                    _("Saved news service to %s") % result.name,
                )
            return
        if not isinstance(panel, PlaylistPanel):
            self._announce_event("playlist", _("Active playlist does not support export"))
            return
        if panel.model.kind is PlaylistKind.FOLDER:
            self._announce_event("playlist", _("Music folder playlists do not support export"))
            return

        dialog = FileSelectionDialog(
            self,
            title=_("Save playlist"),
            message=_("Save playlist"),
            wildcard=_("M3U playlists (*.m3u)|*.m3u|All files|*.*"),
            style=wx.FD_SAVE,
        )
        result = dialog.ShowModal()
        selected_paths = dialog.get_paths() if result == wx.ID_OK else []
        dialog.Destroy()
        if result != wx.ID_OK or not selected_paths:
            return

        path = Path(selected_paths[0])

        try:
            lines = ["#EXTM3U"]
            for item in panel.model.items:
                duration = int(item.duration_seconds) if item.duration_seconds else -1
                lines.append(f"#EXTINF:{duration},{item.title}")
                lines.append(str(item.path.resolve()))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as exc:  # pylint: disable=broad-except
            self._announce_event("import_export", _("Failed to save playlist: %s") % exc)
            return

        self._announce_event("import_export", _("Playlist saved to %s") % path.name)

    def _on_exit(self, event: wx.CommandEvent) -> None:
        try:
            self._audio_engine.stop_all()
        finally:
            self.Close()

    def _on_options(self, event: wx.CommandEvent) -> None:
        current_language = self._settings.get_language()
        dialog = OptionsDialog(self, settings=self._settings, audio_engine=self._audio_engine)
        if dialog.ShowModal() == wx.ID_OK:
            self._settings.save()
            self._fade_duration = max(self._settings.get_playback_fade_seconds(), 0.0)
            self._playback.reload_pfl_device()
            self._alternate_play_next = self._settings.get_alternate_play_next()
            self._swap_play_select = self._settings.get_swap_play_select()
            self._auto_remove_played = self._settings.get_auto_remove_played()
            self._focus_playing_track = self._settings.get_focus_playing_track()
            self._intro_alert_seconds = self._settings.get_intro_alert_seconds()
            self._track_end_alert_seconds = self._settings.get_track_end_alert_seconds()
            self._refresh_news_panels()
            self._apply_swap_play_select_option()
            new_language = self._settings.get_language()
            if new_language != current_language:
                set_language(new_language)
                wx.MessageBox(
                    _("Language change will apply after restarting the application."),
                    _("Information"),
                    parent=self,
                )
        dialog.Destroy()

    def _on_edit_shortcuts(self, _event: wx.CommandEvent) -> None:
        dialog = ShortcutEditorDialog(self, settings=self._settings)
        if dialog.ShowModal() == wx.ID_OK:
            values = dialog.get_values()
            for (scope, action), shortcut in values.items():
                if get_shortcut(scope, action) is None:
                    continue
                self._settings.set_shortcut(scope, action, shortcut)
            self._settings.save()
            self._playlist_hotkey_defaults = self._settings.get_playlist_shortcuts()
            self._refresh_playlist_hotkeys()
            self._update_shortcut_menu_labels()
            self._configure_accelerators()
            self._announce_event("hotkeys", _("Keyboard shortcuts saved"))
        dialog.Destroy()

    def _on_toggle_auto_mix(self, event: wx.CommandEvent) -> None:
        self._set_auto_mix_enabled(not self._auto_mix_enabled)

    def _set_auto_mix_enabled(self, enabled: bool, *, reason: str | None = None) -> None:
        if self._auto_mix_enabled == enabled:
            return
        self._auto_mix_enabled = enabled
        if not enabled:
            self._playback.clear_auto_mix()
        if reason:
            self._announce_event("auto_mix", f"{ANNOUNCEMENT_PREFIX}{reason}")
        else:
            status = _("enabled") if enabled else _("disabled")
            self._announce_event("auto_mix", f"{ANNOUNCEMENT_PREFIX}{_('Auto mix %s') % status}")
        if enabled:
            # jeśli automix włączamy podczas odtwarzania, ustaw tracker na bieżące utwory
            for (pl_id, item_id) in list(getattr(self._playback, "contexts", {}).keys()):
                try:
                    self._auto_mix_tracker.set_last_started(pl_id, item_id)
                except Exception:
                    pass
            panel = self._get_current_music_panel()
            if panel is not None:
                playlist = getattr(panel, "model", None)
                if playlist and self._get_playback_context(playlist.id) is None:
                    items = getattr(playlist, "items", [])
                    if items:
                        target_idx = self._preferred_auto_mix_index(panel, len(items))
                        if not self._auto_mix_start_index(panel, target_idx, restart_playing=False):
                            self._announce_event("playback_events", _("No scheduled tracks available"))
                    else:
                        self._announce_event("playback_events", _("No scheduled tracks available"))

    def _preferred_auto_mix_index(self, panel: PlaylistPanel, item_count: int) -> int:
        try:
            selected = panel.get_selected_indices()
        except Exception:
            selected = []
        idx = selected[0] if selected else None
        if idx is None:
            try:
                focus_idx = panel.get_focused_index()
            except Exception:
                focus_idx = wx.NOT_FOUND
            idx = focus_idx if focus_idx != wx.NOT_FOUND else 0
        idx = max(0, min(idx, max(0, item_count - 1)))
        return idx

    def _on_toggle_loop_playback(self, _event: wx.CommandEvent) -> None:
        # 1) Jeśli gdziekolwiek gra pętla – wyłącz ją globalnie, niezależnie od zaznaczenia/playlisty.
        def _find_active_loop() -> tuple[PlaylistItem, PlaylistModel] | None:
            for (pl_id, item_id), _ctx in self._playback.contexts.items():
                panel = self._playlists.get(pl_id)
                if not isinstance(panel, PlaylistPanel):
                    continue
                item = panel.model.get_item(item_id)
                if item and item.loop_enabled and item.has_loop():
                    return item, panel.model
            return None

        active = _find_active_loop()
        if active:
            playing_item, playing_model = active
            playing_item.loop_enabled = False
            playing_item.loop_auto_enabled = False
            if not save_loop_metadata(
                playing_item.path,
                playing_item.loop_start_seconds,
                playing_item.loop_end_seconds,
                playing_item.loop_enabled,
                playing_item.loop_auto_enabled,
            ):
                self._announce_event("loop", _("Failed to update loop metadata"))
            self._apply_loop_setting_to_playback(playlist_id=playing_model.id, item_id=playing_item.id)
            self._announce_event("loop", _("Track looping disabled"))
            remaining = self._compute_intro_remaining(playing_item)
            if remaining is not None:
                # tylko czas, bez dodatkowych prefiksów
                self._announce_intro_remaining(remaining, prefix_only=True)
            panel = self._playlists.get(playing_model.id)
            current_panel = self._get_current_music_panel()
            if isinstance(panel, PlaylistPanel):
                try:
                    sel = panel.get_selected_indices()
                except Exception:
                    sel = []
                panel.refresh(selected_indices=sel, focus=(current_panel is panel))
            return

        # 2) W przeciwnym razie toggle dotyczy zaznaczonego utworu.
        context = self._get_selected_context()
        if context is None:
            self._announce_event("playlist", _("No track selected"))
            return
        panel, model, indices = context
        idx = indices[0]
        if not (0 <= idx < len(model.items)):
            self._announce_event("playlist", _("No track selected"))
            return
        item = model.items[idx]
        if not item.has_loop():
            self._announce_event("loop", _("Track has no loop defined"))
            return

        item.loop_enabled = not item.loop_enabled
        item.loop_auto_enabled = item.loop_enabled
        if not save_loop_metadata(
            item.path,
            item.loop_start_seconds,
            item.loop_end_seconds,
            item.loop_enabled,
            item.loop_auto_enabled,
        ):
            self._announce_event("loop", _("Failed to update loop metadata"))
        self._apply_loop_setting_to_playback(playlist_id=model.id, item_id=item.id)
        state = _("enabled") if item.loop_enabled else _("disabled")
        self._announce_event("loop", _("Track looping %s") % state)
        if not item.loop_enabled:
            remaining = self._compute_intro_remaining(item)
            if remaining is not None:
                self._announce_intro_remaining(remaining, prefix_only=True)
        panel.refresh(selected_indices=[idx], focus=False)

    def _apply_replay_gain(self, item: PlaylistItem, gain_db: float | None) -> None:
        item.replay_gain_db = gain_db
        if not save_replay_gain_metadata(item.path, gain_db):
            self._announce_event("pfl", _("Failed to update ReplayGain metadata"))
        else:
            self._announce_event("pfl", _("Updated ReplayGain for %s") % item.title)

    def _on_loop_info(self, _event: wx.CommandEvent) -> None:
        context = self._get_selected_context()
        if context is None:
            return
        _panel, model, indices = context
        index = indices[0]
        if not (0 <= index < len(model.items)):
            self._announce_event("playlist", _("No track selected"))
            return
        item = model.items[index]
        messages: list[str] = []
        if item.has_loop():
            start = item.loop_start_seconds or 0.0
            end = item.loop_end_seconds or 0.0
            state = _("active") if item.loop_enabled else _("disabled")
            messages.append(_("Loop from %.2f to %.2f seconds, looping %s") % (start, end, state))
        else:
            messages.append(_("Track has no loop defined"))

        intro = item.intro_seconds
        if intro is not None:
            cue = item.cue_in_seconds or 0.0
            intro_length = max(0.0, intro - cue)
            messages.append(_("Intro length: {seconds:.1f} seconds").format(seconds=intro_length))
        else:
            messages.append(_("Intro not defined"))

        self._announce_event("loop", ". ".join(messages))

    def _on_track_remaining(self, _event: wx.CommandEvent | None = None) -> None:
        info = self._resolve_remaining_playback()
        if info is None:
            self._announce_event("playback_events", _("No active playback to report remaining time"))
            return
        playlist, item, remaining = info
        if item.effective_duration_seconds <= 0:
            self._announce_event("playback_events", _("Remaining time unavailable for %s") % item.title)
            return
        total_seconds = max(0, int(round(remaining)))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            time_text = f"{hours:d}:{minutes:02d}:{seconds:02d}"
        else:
            time_text = f"{minutes:02d}:{seconds:02d}"
        # Najpierw czas, następnie (jeśli aktywna) informacja o pętli, potem kontekst
        parts: list[str] = [time_text]
        if item.loop_enabled and item.has_loop():
            parts.append(_("Loop enabled"))
        parts.append(_("Track: %(track)s. Playlist: %(playlist)s.") % {"track": item.title, "playlist": playlist.name})
        self._announce_event("playback_events", " ".join(parts))

    def _apply_loop_setting_to_playback(self, *, playlist_id: str | None = None, item_id: str | None = None) -> None:
        for (pl_id, item_id_key), context in list(self._playback.contexts.items()):
            if playlist_id is not None and pl_id != playlist_id:
                continue
            if item_id is not None and item_id_key != item_id:
                continue

            playlist = self._get_playlist_model(pl_id)
            if not playlist:
                continue
            item = playlist.get_item(item_id_key)
            if not item:
                continue
            try:
                if item.loop_enabled and item.has_loop():
                    context.player.set_loop(item.loop_start_seconds, item.loop_end_seconds)
                else:
                    context.player.set_loop(None, None)
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("Failed to synchronise playback loop: %s", exc)
            self._sync_loop_mix_trigger(panel=self._playlists.get(pl_id), playlist=playlist, item=item, context=context)

    def _sync_loop_mix_trigger(
        self,
        *,
        panel: PlaylistPanel | None,
        playlist: PlaylistModel,
        item: PlaylistItem,
        context: PlaybackContext,
    ) -> None:
        key = (playlist.id, item.id)
        if item.loop_enabled and item.has_loop():
            self._playback.auto_mix_state[key] = "loop_hold"
            self._playback.update_mix_trigger(
                playlist.id,
                item.id,
                mix_trigger_seconds=None,
                on_mix_trigger=None,
            )
            self._clear_mix_plan(playlist.id, item.id)
            logger.debug("UI: loop_hold active, mix trigger cleared playlist=%s item=%s", playlist.id, item.id)
            return

        if self._playback.auto_mix_state.get(key) == "loop_hold":
            self._playback.auto_mix_state.pop(key, None)

        effective_override = None
        getter = getattr(context.player, "get_length_seconds", None)
        if getter:
            try:
                total_len = float(getter())
                if total_len > 0.0:
                    effective_override = max(0.0, total_len - (item.cue_in_seconds or 0.0))
            except Exception:
                effective_override = None

        native_trigger = self._supports_mix_trigger(context.player)
        mix_at, fade_seconds, base_cue, effective_duration = self._resolve_mix_timing(
            item,
            effective_duration_override=effective_override,
        )
        if mix_at is None:
            self._clear_mix_plan(playlist.id, item.id)
            return
        current_abs = (item.cue_in_seconds or 0.0) + (item.current_position or 0.0)
        if current_abs >= mix_at - 0.05:
            logger.debug(
                "UI: loop disabled but mix point already passed playlist=%s item=%s current=%.3f mix_at=%.3f -> no trigger",
                playlist.id,
                item.id,
                current_abs,
                mix_at,
            )
            return
        self._register_mix_plan(
            playlist.id,
            item.id,
            mix_at=mix_at,
            fade_seconds=fade_seconds,
            base_cue=base_cue,
            effective_duration=effective_duration,
            native_trigger=native_trigger,
        )
        if native_trigger:
            self._playback.update_mix_trigger(
                playlist.id,
                item.id,
                mix_trigger_seconds=mix_at,
                on_mix_trigger=(lambda: self._auto_mix_now(playlist, item, panel)) if panel else None,
            )
        logger.debug(
            "UI: loop disabled -> rescheduled mix trigger playlist=%s item=%s mix_at=%.3f fade=%.3f current=%.3f native=%s",
            playlist.id,
            item.id,
            mix_at,
            fade_seconds,
            current_abs,
            native_trigger,
        )

    def _apply_mix_trigger_to_playback(self, *, playlist_id: str, item: PlaylistItem, panel: PlaylistPanel) -> None:
        if item.break_after:
            cleared = self._playback.update_mix_trigger(
                playlist_id,
                item.id,
                mix_trigger_seconds=None,
                on_mix_trigger=None,
            )
            if cleared:
                logger.debug("UI: cleared mix trigger for break item playlist=%s item=%s", playlist_id, item.id)
            self._clear_mix_plan(playlist_id, item.id)
            return

        ctx = self._playback.contexts.get((playlist_id, item.id))
        effective_override = None
        if ctx:
            getter = getattr(ctx.player, "get_length_seconds", None)
            if getter:
                try:
                    total_len = float(getter())
                    effective_override = max(0.0, total_len - (item.cue_in_seconds or 0.0))
                except Exception:
                    pass

        mix_trigger_seconds, fade_seconds, base_cue, effective_duration = self._resolve_mix_timing(
            item,
            effective_duration_override=effective_override,
        )
        native_trigger = self._supports_mix_trigger(ctx.player if ctx else None)
        self._register_mix_plan(
            playlist_id,
            item.id,
            mix_at=mix_trigger_seconds,
            fade_seconds=fade_seconds,
            base_cue=base_cue,
            effective_duration=effective_duration,
            native_trigger=native_trigger,
        )
        updated = False
        if native_trigger and mix_trigger_seconds is not None:
            updated = self._playback.update_mix_trigger(
                playlist_id,
                item.id,
                mix_trigger_seconds=mix_trigger_seconds,
                on_mix_trigger=lambda: self._auto_mix_now(panel.model, item, panel),
            )
        logger.debug(
            "UI: rescheduled mix trigger playlist=%s item=%s mix_at=%s fade=%.3f native=%s applied=%s",
            playlist_id,
            item.id,
            f"{mix_trigger_seconds:.3f}" if mix_trigger_seconds is not None else "None",
            fade_seconds,
            native_trigger,
            updated,
        )

    def _on_toggle_selection(self, playlist_id: str, item_id: str) -> None:
        if self._auto_mix_enabled:
            self._announce_event("selection", _("Disable auto mix to queue specific tracks"))
            return
        playlist = self._get_playlist_model(playlist_id)
        if not playlist:
            return
        selected = playlist.toggle_selection(item_id)
        panel = self._playlists.get(playlist_id)
        if panel is not None:
            try:
                index = next(idx for idx, track in enumerate(panel.model.items) if track.id == item_id)
            except StopIteration:
                indices = None
            else:
                indices = [index]
            panel.refresh(indices, focus=bool(indices))
        item = playlist.get_item(item_id)
        if selected:
            # selekcja nie wypowiada dodatkowych informacji (loop jest ogłaszany przy ruchu fokusu)
            pass
        else:
            self._announce_event("selection", _("Selection removed from %s") % item.title)

    def _auto_mix_play_next(self, panel: PlaylistPanel) -> bool:
        """Play Next w automixie: gra kolejny utwór sekwencyjnie; break przechodzi dalej (z zawijaniem)."""
        playlist = panel.model
        if not playlist.items:
            return False

        # jeśli aktywna jest pętla z loop_hold – zatrzymaj ją z fade i przesuń kursor,
        # aby kolejny indeks wskazywał następny element zamiast restartować bed
        loop_hold_keys = [
            key
            for key, state in self._playback.auto_mix_state.items()
            if state == "loop_hold" and key[0] == playlist.id
        ]
        if loop_hold_keys:
            stopped = False
            try:
                self._stop_playlist_playback(
                    playlist.id,
                    mark_played=True,
                    fade_duration=max(0.0, self._fade_duration),
                )
                stopped = True
            except Exception:
                logger.debug("UI: failed to stop loop_hold playback playlist=%s", playlist.id)
            finally:
                for key in loop_hold_keys:
                    self._playback.auto_mix_state.pop(key, None)
            if stopped:
                last_loop_item_id = loop_hold_keys[-1][1]
                self._last_started_item_id[playlist.id] = last_loop_item_id
                try:
                    self._auto_mix_tracker.set_last_started(playlist.id, last_loop_item_id)
                except Exception:
                    logger.debug(
                        "UI: failed to update auto-mix tracker after loop_hold stop playlist=%s item=%s",
                        playlist.id,
                        last_loop_item_id,
                    )

        if self._auto_mix_busy.get(playlist.id):
            logger.debug("UI: automix play_next ignored (busy) playlist=%s", playlist.id)
            return False
        self._auto_mix_busy[playlist.id] = True
        result = False
        try:
            # konsumuj ewentualne breaki na już zagranych utworach, aby nie zatrzymywały kolejnych przebiegów
            for track in playlist.items:
                if track.status is PlaylistItemStatus.PLAYED and track.break_after:
                    track.break_after = False

            total = len(playlist.items)

            # Jeśli obecnie gra utwór z breakiem i użytkownik wywoła Play Next – potraktuj break jak zakończony.
            current_ctx = self._get_playback_context(playlist.id)
            if current_ctx:
                key, _ctx = current_ctx
                playing_item = playlist.get_item(key[1])
                if playing_item and playing_item.break_after and playing_item.status is PlaylistItemStatus.PLAYING:
                    idx_playing = self._index_of_item(playlist, playing_item.id) or 0
                    next_idx = (idx_playing + 1) % len(playlist.items)
                    playing_item.break_after = False
                    playing_item.is_selected = False
                    playing_item.status = PlaylistItemStatus.PLAYED
                    playing_item.current_position = playing_item.effective_duration_seconds
                    playlist.break_resume_index = next_idx
                    self._active_break_item.pop(playlist.id, None)
                    self._stop_playlist_playback(
                        playlist.id,
                        mark_played=True,
                        fade_duration=max(0.0, self._fade_duration),
                    )
                    self._auto_mix_tracker.set_last_started(playlist.id, playlist.items[next_idx].id)
                    result = self._auto_mix_start_index(panel, next_idx, restart_playing=False)
                    return result

            idx = self._auto_mix_tracker.next_index(playlist, break_resume_index=playlist.break_resume_index)
            playlist.break_resume_index = None

            # jeśli wybrany indeks to aktualnie grający utwór, przeskocz dalej, by uniknąć restartu
            current_ctx = self._get_playback_context(playlist.id)
            if current_ctx:
                key, ctx = current_ctx
                current_item_id = key[1]
                try_playing = playlist.items[idx]
                if try_playing.id == current_item_id:
                    for _ in range(len(playlist.items)):
                        idx = (idx + 1) % len(playlist.items)
                        if playlist.items[idx].id != current_item_id and playlist.items[idx].status is not PlaylistItemStatus.PLAYING:
                            break

            logger.debug(
                "UI: automix play_next choose idx=%s total=%s last=%s",
                idx,
                total,
                self._auto_mix_tracker._last_item_id.get(playlist.id),
            )
            # zapamiętaj kandydat przed startem; commit nastąpi po starcie
            self._auto_mix_tracker.stage_next(playlist.id, playlist.items[idx].id)
            result = self._auto_mix_start_index(panel, idx, restart_playing=False)
            return result
        finally:
            self._auto_mix_busy[playlist.id] = False

    def _on_mix_points_configure(self, playlist_id: str, item_id: str) -> None:
        panel = self._playlists.get(playlist_id)
        if panel is None:
            return
        item = next((track for track in panel.model.items if track.id == item_id), None)
        if item is None:
            return

        dialog = MixPointEditorDialog(
            self,
            title=_("Mix points – %s") % item.title,
            duration_seconds=item.duration_seconds,
            cue_in_seconds=item.cue_in_seconds,
            intro_seconds=item.intro_seconds,
            outro_seconds=item.outro_seconds,
            segue_seconds=item.segue_seconds,
            segue_fade_seconds=item.segue_fade_seconds,
            overlap_seconds=item.overlap_seconds,
            on_preview=lambda position, loop_range=None: self._playback.start_preview(
                item,
                max(0.0, position),
                loop_range=loop_range,
            ),
            on_mix_preview=lambda values: self._preview_mix_with_next(panel.model, item, overrides=values),
            on_stop_preview=self._stop_preview,
            track_path=item.path,
            initial_replay_gain=item.replay_gain_db,
            on_replay_gain_update=lambda gain, item=item: self._apply_replay_gain(item, gain),
            loop_start_seconds=item.loop_start_seconds,
            loop_end_seconds=item.loop_end_seconds,
            loop_enabled=item.loop_enabled,
            loop_auto_enabled=item.loop_auto_enabled,
            default_fade_seconds=self._fade_duration,
        )

        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            result = dialog.get_result()
        finally:
            dialog.Destroy()
            self._stop_preview()

        mix_values = {
            "cue_in": result.get("cue"),
            "intro": result.get("intro"),
            "outro": result.get("outro"),
            "segue": result.get("segue"),
            "segue_fade": result.get("segue_fade"),
            "overlap": result.get("overlap"),
        }

        item.cue_in_seconds = mix_values["cue_in"]
        item.intro_seconds = mix_values["intro"]
        item.outro_seconds = mix_values["outro"]
        item.segue_seconds = mix_values["segue"]
        item.segue_fade_seconds = mix_values["segue_fade"]
        item.overlap_seconds = mix_values["overlap"]

        if not save_mix_metadata(
            item.path,
            cue_in=item.cue_in_seconds,
            intro=item.intro_seconds,
            outro=item.outro_seconds,
            segue=item.segue_seconds,
            segue_fade=item.segue_fade_seconds,
            overlap=item.overlap_seconds,
        ):
            self._announce_event("pfl", _("Failed to update mix metadata"))
        else:
            self._announce_event("pfl", _("Updated mix points for %s") % item.title)
            self._propagate_mix_points_for_path(
                path=item.path,
                mix_values=mix_values,
                source_playlist_id=playlist_id,
                source_item_id=item.id,
            )

        panel.refresh()
        self._apply_mix_trigger_to_playback(playlist_id=playlist_id, item=item, panel=panel)

        loop_info = result.get("loop") or {}
        loop_defined = bool(loop_info.get("enabled"))
        loop_start = loop_info.get("start")
        loop_end = loop_info.get("end")
        loop_auto_enabled = bool(result.get("loop_auto_enabled"))
        if loop_defined and loop_start is not None and loop_end is not None and loop_end > loop_start:
            try:
                item.set_loop(loop_start, loop_end)
            except ValueError as exc:
                self._announce_event("loop", str(exc))
            else:
                item.loop_auto_enabled = loop_auto_enabled
                item.loop_enabled = loop_auto_enabled or item.loop_enabled
                if not save_loop_metadata(
                    item.path,
                    loop_start,
                    loop_end,
                    item.loop_enabled,
                    item.loop_auto_enabled,
                ):
                    self._announce_event("loop", _("Failed to update loop metadata"))
                self._apply_loop_setting_to_playback(playlist_id=playlist_id, item_id=item.id)
                panel.refresh()
        else:
            if item.has_loop() or item.loop_enabled:
                item.clear_loop()
                item.loop_auto_enabled = False
                save_loop_metadata(item.path, None, None, auto_enabled=False)
                self._apply_loop_setting_to_playback(playlist_id=playlist_id, item_id=item.id)
                panel.refresh()

    def _propagate_mix_points_for_path(
        self,
        *,
        path: Path,
        mix_values: dict[str, float | None],
        source_playlist_id: str,
        source_item_id: str,
    ) -> None:
        context_map = getattr(self._playback, "contexts", {}) if hasattr(self._playback, "contexts") else {}
        refreshed: set[str] = set()
        for pl_id, panel in self._playlists.items():
            playlist = getattr(panel, "model", None)
            if playlist is None:
                continue
            updated = False
            for track in playlist.items:
                if track.path != path or (pl_id == source_playlist_id and track.id == source_item_id):
                    continue
                changed = False
                for key, attr in (
                    ("cue_in", "cue_in_seconds"),
                    ("intro", "intro_seconds"),
                    ("outro", "outro_seconds"),
                    ("segue", "segue_seconds"),
                    ("segue_fade", "segue_fade_seconds"),
                    ("overlap", "overlap_seconds"),
                ):
                    new_val = mix_values.get(key)
                    if getattr(track, attr) != new_val:
                        setattr(track, attr, new_val)
                        changed = True
                if changed:
                    updated = True
                    key = (pl_id, track.id)
                    if context_map.get(key):
                        self._apply_mix_trigger_to_playback(playlist_id=pl_id, item=track, panel=panel)
                    else:
                        self._clear_mix_plan(pl_id, track.id)
            if updated and hasattr(panel, "refresh"):
                if pl_id not in refreshed:
                    try:
                        panel.refresh()
                    except TypeError:
                        panel.refresh()
                    refreshed.add(pl_id)

    def _start_playback(
        self,
        panel: PlaylistPanel,
        item: PlaylistItem,
        *,
        restart_playing: bool = False,
        auto_mix_sequence: bool = False,
        prefer_overlap: bool = False,
    ) -> bool:
        playlist = panel.model
        key = (playlist.id, item.id)
        # stop any preview playback before starting actual playback
        self._stop_preview()

        # w automixie blokuj ręczne starty spoza sekwencji; dopuszczaj restart tylko w automixowej ścieżce
        if (
            self._auto_mix_enabled
            and playlist.kind is PlaylistKind.MUSIC
            and not auto_mix_sequence
            and not restart_playing
        ):
            logger.debug("UI: automix ignoring manual start for item=%s", item.id)
            return False

        # automix: jeśli już gra ten sam utwór i to sekwencja automix, nie restartuj
        if auto_mix_sequence and item.status is PlaylistItemStatus.PLAYING:
            ctx = self._playback.contexts.get(key)
            if ctx:
                try:
                    if ctx.player.is_playing():
                        logger.debug("UI: automix sequence ignoring restart of already playing item=%s", item.id)
                        return True
                except Exception:
                    pass

        # W automixie ignoruj żądania startu utworów już oznaczonych jako PLAYED – nie ruszaj bieżącego grania.
        if (
            self._auto_mix_enabled
            and playlist.kind is PlaylistKind.MUSIC
            and item.status is PlaylistItemStatus.PLAYED
            and not restart_playing
        ):
            logger.debug("UI: automix ignoring start for PLAYED item=%s (no restart)", item.id)
            return False

        if not item.path.exists():
            item.status = PlaylistItemStatus.PENDING
            panel.mark_item_status(item.id, item.status)
            panel.refresh()
            self._announce_event("playback_errors", _("File %s does not exist") % item.path)
            return False

        context = self._playback.contexts.get(key)
        logger.debug(
            "UI: start playback request playlist=%s item=%s existing_context=%s device=%s slot=%s",
            playlist.id,
            item.id,
            bool(context),
            getattr(context, "device_id", None),
            getattr(context, "slot_index", None),
        )
        player = context.player if context else None
        device_id = context.device_id if context else None
        slot_index = context.slot_index if context else None

        if player is None or device_id is None or slot_index is None:
            existing_context = self._get_playback_context(playlist.id)
            if existing_context:
                existing_key, _existing = existing_context
                crossfade_active = prefer_overlap or bool(self._playback.auto_mix_state.get(existing_key))
                logger.debug(
                    "UI: stopping existing context for playlist %s crossfade_active=%s",
                    playlist.id,
                    crossfade_active,
                )
                if not crossfade_active:
                    fade_seconds = self._fade_duration
                    self._stop_playlist_playback(playlist.id, mark_played=True, fade_duration=fade_seconds)

        def _on_finished(finished_item_id: str) -> None:
            app = wx.GetApp()
            if app:
                wx.CallAfter(self._handle_playback_finished, playlist.id, finished_item_id)
            else:  # defensive: allow playback controller use without wx.App
                self._handle_playback_finished(playlist.id, finished_item_id)

        def _on_progress(progress_item_id: str, seconds: float) -> None:
            app = wx.GetApp()
            if app:
                wx.CallAfter(self._handle_playback_progress, playlist.id, progress_item_id, seconds)
            else:
                self._handle_playback_progress(playlist.id, progress_item_id, seconds)

        start_seconds = item.cue_in_seconds or 0.0
        logger.debug("UI: invoking playback controller for item %s at %.3fs", item.id, start_seconds)

        try:
            notify_nvda_play_next()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("NVDA play-next notify failed: %s", exc)

        # Automix: jeżeli próba zagrania już PLAYED, przeskocz do kolejnego w sekwencji.
        if self._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC and item.status is PlaylistItemStatus.PLAYED:
            logger.debug("UI: automix skip PLAYED item=%s -> force next sequence", item.id)
            total = len(playlist.items)
            if total == 0:
                return False
            next_idx = self._auto_mix_tracker.next_index(playlist, break_resume_index=playlist.break_resume_index)
            playlist.break_resume_index = None
            logger.debug(
                "UI: automix skip PLAYED -> start idx=%s last=%s break_resume=%s",
                next_idx,
                self._auto_mix_tracker._last_item_id.get(playlist.id),
                playlist.break_resume_index,
            )
            return self._auto_mix_start_index(
                panel,
                next_idx,
                restart_playing=restart_playing,
                overlap_trigger=prefer_overlap,
            )

        # auto-mix trigger: wyzwól na określonym czasie (segoue/outro/overlap)
        mix_trigger_seconds: float | None
        fade_seconds: float = 0.0
        base_cue: float = item.cue_in_seconds or 0.0
        effective_duration: float = item.effective_duration_seconds

        if playlist.kind is PlaylistKind.MUSIC and item.break_after:
            mix_trigger_seconds = None
            on_mix_trigger: Callable[[], None] | None = None
        else:
            effective_override = None
            ctx = self._playback.contexts.get((playlist.id, item.id))
            if ctx:
                getter = getattr(ctx.player, "get_length_seconds", None)
                if getter:
                    try:
                        total_len = float(getter())
                        effective_override = max(0.0, total_len - base_cue)
                        length_diff = abs(effective_override - effective_duration)
                        if length_diff > 0.5:
                            logger.debug(
                                "UI: adjusting mix timing with player length playlist=%s item=%s meta_eff=%.3f real_eff=%.3f",
                                playlist.id,
                                item.id,
                                effective_duration,
                                effective_override,
                            )
                    except Exception:
                        pass
            mix_trigger_seconds, fade_seconds, base_cue, effective_duration = self._resolve_mix_timing(
                item,
                effective_duration_override=effective_override,
            )
            on_mix_trigger = lambda: self._auto_mix_now(playlist, item, panel)

        try:
            result = self._playback.start_item(
                playlist,
                item,
                start_seconds=start_seconds,
                on_finished=_on_finished,
                on_progress=_on_progress,
                restart_if_playing=restart_playing,
                mix_trigger_seconds=mix_trigger_seconds,
                on_mix_trigger=on_mix_trigger,
            )
            logger.debug(
                "UI: mix trigger scheduled item=%s mix_at=%s fade=%.3f cue=%.3f effective=%.3f seg=%s ovl=%s",
                item.id,
                f"{mix_trigger_seconds:.3f}" if mix_trigger_seconds is not None else "None",
                fade_seconds,
                base_cue,
                effective_duration,
                getattr(item, 'segue_seconds', None),
                getattr(item, 'overlap_seconds', None),
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception(
                "UI: start_item failed for playlist=%s item_id=%s title=%s err=%s",
                playlist.id,
                item.id,
                getattr(item, "title", item.id),
                exc,
            )
            return False
        if result is None:
            item.status = PlaylistItemStatus.PENDING
            panel.mark_item_status(item.id, item.status)
            panel.refresh()
            return False
        logger.debug(
            "UI: playback started playlist=%s item=%s device=%s slot=%s",
            playlist.id,
            item.id,
            device_id or getattr(result, "device_id", None),
            slot_index or getattr(result, "slot_index", None),
        )
        native_trigger = self._supports_mix_trigger(result.player)
        self._register_mix_plan(
            playlist.id,
            item.id,
            mix_at=mix_trigger_seconds,
            fade_seconds=fade_seconds,
            base_cue=base_cue,
            effective_duration=effective_duration,
            native_trigger=native_trigger,
        )
        self._adjust_duration_and_mix_trigger(panel, playlist, item, result)

        previous_selection = panel.get_selected_indices()
        previous_focus = panel.get_focused_index()

        panel.mark_item_status(item.id, PlaylistItemStatus.PLAYING)
        # automix: ustaw selekcję na grający utwór tylko przy starcie; później użytkownik może nawigować strzałkami
        if self._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC and self._focus_playing_track:
            idx = playlist.index_of(item.id)
            if idx >= 0:
                panel.refresh(selected_indices=[idx], focus=True)
            else:
                panel.refresh(focus=False)
        else:
            # gdy follow-playing jest wyłączone, nie ruszaj selekcji ani fokusu
            if self._focus_playing_track:
                panel.refresh(focus=False)
            else:
                if previous_selection:
                    panel.refresh(selected_indices=previous_selection, focus=True)
                elif previous_focus != wx.NOT_FOUND and 0 <= previous_focus < len(playlist.items):
                    # brak selekcji – przywróć focus na poprzedni wiersz
                    panel.refresh(focus=False)
                    panel.select_index(previous_focus, focus=True)
                else:
                    panel.refresh(focus=False)
        self._focus_lock[playlist.id] = False
        self._last_started_item_id[playlist.id] = item.id
        # Jeśli utwór ma break, zapamiętaj w stanie, żeby nie wyzwalać mixu.
        if playlist.kind is PlaylistKind.MUSIC and item.break_after:
            self._playback.auto_mix_state[(playlist.id, item.id)] = "break_halt"
            self._active_break_item[playlist.id] = item.id
        self._sync_loop_mix_trigger(panel=panel, playlist=playlist, item=item, context=result)
        self._maybe_focus_playing_item(panel, item.id)
        if item.has_loop() and item.loop_enabled:
            self._announce_event("loop", _("Loop playing"))
        return True

    def _adjust_duration_and_mix_trigger(
        self,
        panel: PlaylistPanel,
        playlist: PlaylistModel,
        item: PlaylistItem,
        context: PlaybackContext,
    ) -> None:
        getter = getattr(context.player, "get_length_seconds", None)
        if not getter:
            return
        try:
            length_seconds = float(getter())
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("UI: failed to read track length from player: %s", exc)
            return
        if length_seconds <= 0:
            return
        cue = item.cue_in_seconds or 0.0
        effective_actual = max(0.0, length_seconds - cue)
        effective_meta = item.effective_duration_seconds
        if abs(effective_actual - effective_meta) <= 0.5:
            return
        item.duration_seconds = cue + effective_actual
        item.current_position = min(item.current_position, effective_actual)
        logger.debug(
            "UI: adjusted duration from player playlist=%s item=%s effective_meta=%.3f effective_real=%.3f cue=%.3f",
            playlist.id,
            item.id,
            effective_meta,
            effective_actual,
            cue,
        )
        if not item.break_after and not (item.loop_enabled and item.has_loop()):
            self._apply_mix_trigger_to_playback(playlist_id=playlist.id, item=item, panel=panel)

    def _start_next_from_playlist(
        self,
        panel: PlaylistPanel,
        *,
        ignore_ui_selection: bool = False,
        advance_focus: bool = True,
        restart_playing: bool = False,
        force_automix_sequence: bool = False,
        prefer_overlap: bool = False,
    ) -> bool:
        playlist = panel.model
        if not playlist.items:
            self._announce_event("playlist", _("Playlist %s is empty") % playlist.name)
            return False

        # W automixie ignorujemy fokus/zaznaczenia – zawsze sekwencja.
        if (
            self._auto_mix_enabled
            and playlist.kind is PlaylistKind.MUSIC
            and not force_automix_sequence
            and not ignore_ui_selection
        ):
            return self._auto_mix_play_next(panel)

        # Wymuszenie sekwencyjnego automix (używane przez Play Next / mix trigger).
        if force_automix_sequence and self._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC:
            total = len(playlist.items)
            if total == 0:
                return False

            # prefer aktualnie grający indeks, żeby uniknąć restartu bieżącego utworu
            current_ctx = self._get_playback_context(playlist.id)
            current_idx = None
            if current_ctx:
                current_idx = self._index_of_item(playlist, current_ctx[0][1])

            if total == 1:
                if current_ctx:
                    # jedna pozycja i już gra -> nie restartuj ani nie zawijaj
                    return True
                next_idx = 0
            elif current_idx is not None and current_idx >= 0:
                next_idx = (current_idx + 1) % total
            else:
                next_idx = self._auto_mix_tracker.next_index(playlist, break_resume_index=playlist.break_resume_index)
            playlist.break_resume_index = None

            logger.debug(
                "UI: automix sequence -> idx=%s id=%s total=%s last=%s",
                next_idx,
                getattr(playlist.items[next_idx], "id", None),
                total,
                self._auto_mix_tracker._last_item_id.get(playlist.id),
            )
            self._auto_mix_tracker.stage_next(playlist.id, playlist.items[next_idx].id)

            # nie restartuj aktualnie grającego utworu – wybierz kolejny pending
            current_ctx = self._get_playback_context(playlist.id)
            if (
                current_ctx
                and current_ctx[0][1] == playlist.items[next_idx].id
                and playlist.items[next_idx].status is PlaylistItemStatus.PLAYING
            ):
                next_idx = (next_idx + 1) % total
                logger.debug(
                    "UI: automix sequence skipping current playing item, advancing to idx=%s id=%s",
                    next_idx,
                    getattr(playlist.items[next_idx], "id", None),
                )
                if playlist.items[next_idx].status is PlaylistItemStatus.PLAYING:
                    logger.debug("UI: automix sequence found no non-playing item to start; aborting mix")
                    return True

            return self._auto_mix_start_index(
                panel,
                next_idx,
                restart_playing=restart_playing,
                overlap_trigger=prefer_overlap,
            )

        # Jeśli automix jest aktywny, bieżący utwór ma break i nadal gra – przeskocz go natychmiast (czysta sekwencja).
        if self._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC:
            current_ctx = self._get_playback_context(playlist.id)
            if current_ctx:
                key, _ctx = current_ctx
                playing_item = playlist.get_item(key[1])
                if playing_item and playing_item.break_after and playing_item.status is PlaylistItemStatus.PLAYING:
                    idx_playing = self._index_of_item(playlist, playing_item.id) or -1
                    next_idx = (idx_playing + 1) % len(playlist.items)
                    playing_item.break_after = False
                    playing_item.is_selected = False
                    playing_item.status = PlaylistItemStatus.PLAYED
                    playing_item.current_position = playing_item.effective_duration_seconds
                    panel.refresh(focus=False)
                    self._stop_playlist_playback(
                        playlist.id,
                        mark_played=True,
                        fade_duration=max(0.0, self._fade_duration),
                    )
                    self._auto_mix_tracker.set_last_started(playlist.id, playlist.items[next_idx].id)
            return self._auto_mix_start_index(
                panel,
                next_idx,
                restart_playing=False,
                overlap_trigger=prefer_overlap,
            )

        consumed_model_selection = False
        preferred_item_id = playlist.next_selected_item_id()
        play_index: int | None = None

        used_ui_selection = False
        break_target_index: int | None = None
        if playlist.kind is PlaylistKind.MUSIC and playlist.break_resume_index is not None:
            # w trybie automix break jest już obsłużony wyżej; tutaj wyczyść i przejdź dalej
            break_target_index = playlist.break_resume_index
            playlist.break_resume_index = None

        if preferred_item_id:
            consumed_model_selection = True
            play_index = self._index_of_item(playlist, preferred_item_id)
        else:
            if break_target_index is not None:
                play_index = next(
                    (
                        idx
                        for idx in range(break_target_index, len(playlist.items))
                        if playlist.items[idx].status is PlaylistItemStatus.PENDING
                    ),
                    None,
                )
            # jeśli brak celu z breaka, a ostatnio grany utwór jest PLAYED, wybierz pierwszy pending za nim
            if play_index is None and playlist.kind is PlaylistKind.MUSIC:
                last_id = self._last_started_item_id.get(playlist.id)
                if last_id:
                    last_idx = self._index_of_item(playlist, last_id)
                    last_item = playlist.get_item(last_id)
                    if last_idx is not None and last_item and last_item.status is PlaylistItemStatus.PLAYED:
                        play_index = next(
                            (
                                idx
                                for idx in range(last_idx + 1, len(playlist.items))
                                if playlist.items[idx].status is PlaylistItemStatus.PENDING
                            ),
                            None,
                        )
            if play_index is None:
                if not ignore_ui_selection:
                    selected_indices = [
                        idx
                        for idx in panel.get_selected_indices()
                        if 0 <= idx < len(playlist.items)
                        and playlist.items[idx].status in (PlaylistItemStatus.PENDING, PlaylistItemStatus.PAUSED)
                    ]
                else:
                    selected_indices = []
                if selected_indices:
                    play_index = selected_indices[0]
                    used_ui_selection = True
                elif not ignore_ui_selection:
                    focus_index = panel.get_focused_index()
                    if focus_index != wx.NOT_FOUND and 0 <= focus_index < len(playlist.items):
                        focus_item = playlist.items[focus_index]
                        if focus_item.status in (PlaylistItemStatus.PENDING, PlaylistItemStatus.PAUSED):
                            play_index = focus_index
                            used_ui_selection = True
                        else:
                            play_index = self._derive_next_play_index(playlist)
                    else:
                        play_index = self._derive_next_play_index(playlist)
                else:
                    play_index = self._derive_next_play_index(playlist)
            if play_index is not None and 0 <= play_index < len(playlist.items):
                preferred_item_id = playlist.items[play_index].id
            else:
                preferred_item_id = None

        # Jeśli wybrany indeks nie jest pending/paused, przeskocz do kolejnego pending.
        if play_index is not None:
            def _next_pending(start_idx: int) -> int | None:
                for idx in range(start_idx, len(playlist.items)):
                    if playlist.items[idx].status in (PlaylistItemStatus.PENDING, PlaylistItemStatus.PAUSED):
                        return idx
                return None

            if not (0 <= play_index < len(playlist.items) and playlist.items[play_index].status in (PlaylistItemStatus.PENDING, PlaylistItemStatus.PAUSED)):
                play_index = _next_pending((play_index + 1) if play_index is not None else 0)
                preferred_item_id = playlist.items[play_index].id if play_index is not None else None
        logger.debug(
            "UI: start_next playlist=%s preferred=%s play_index=%s used_ui=%s consumed_selection=%s ignore_ui=%s",
            playlist.id,
            preferred_item_id,
            play_index,
            used_ui_selection,
            consumed_model_selection,
            ignore_ui_selection,
        )

        if restart_playing:
            current_ctx = self._playback.get_context(playlist.id)
            if current_ctx and preferred_item_id == current_ctx[0][1]:
                logger.debug(
                    "UI: auto-mix avoiding restart of current item=%s, picking next pending",
                    preferred_item_id,
                )
                # zamiast restartować bieżący utwór, wybierz następny pending z kolejki
                play_index = self._derive_next_play_index(playlist)
                preferred_item_id = playlist.items[play_index].id if play_index is not None else None
                consumed_model_selection = False

        # Tryb ręczny: pozwól ponownie zagrać wybrany utwór nawet jeśli jest PLAYED.
        if not self._auto_mix_enabled and preferred_item_id:
            preferred_item = playlist.get_item(preferred_item_id)
            if preferred_item and preferred_item.status is PlaylistItemStatus.PLAYED:
                preferred_item.status = PlaylistItemStatus.PENDING
                preferred_item.current_position = 0.0

        item = playlist.begin_next_item(preferred_item_id)
        if not item:
            self._announce_event("playback_events", _("No scheduled tracks in playlist %s") % playlist.name)
            return False

        current_ctx = self._playback.get_context(playlist.id)
        if (
            current_ctx
            and current_ctx[0][1] == item.id
            and item.status is PlaylistItemStatus.PLAYING
            and not restart_playing
        ):
            logger.debug(
                "UI: item %s already playing on playlist %s and restart_playing=False -> skipping new start",
                item.id,
                playlist.id,
            )
            return True

        if self._start_playback(panel, item, restart_playing=restart_playing):
            self._last_started_item_id[playlist.id] = item.id
            if playlist.kind is PlaylistKind.MUSIC and self._auto_mix_enabled:
                self._auto_mix_tracker.set_last_started(playlist.id, item.id)
            track_name = self._format_track_name(item)
            if used_ui_selection or consumed_model_selection or item.id == preferred_item_id:
                if self._focus_playing_track:
                    logger.debug(
                        "UI: clearing selection for started item=%s playlist=%s (used_ui=%s consumed_model=%s)",
                        item.id,
                        playlist.id,
                        used_ui_selection,
                        consumed_model_selection,
                    )
                    playlist.clear_selection(item.id)
                    self._refresh_selection_display(playlist.id)
            if advance_focus and not consumed_model_selection and not used_ui_selection:
                # jeśli follow_playing_track jest wyłączone, nie zmieniaj selekcji; inaczej ustaw ją na kolejny utwór
                if self._focus_playing_track:
                    next_focus = self._derive_next_play_index(playlist)
                    if next_focus is not None and 0 <= next_focus < len(playlist.items):
                        panel.select_index(next_focus, focus=False)
            status_message = _("Playing %s from playlist %s") % (track_name, playlist.name)
            self._announce_event(
                "playback_events",
                status_message,
                spoken_message="",
            )
            return True
        return False

    def _derive_next_play_index(self, playlist: PlaylistModel) -> int | None:
        if not playlist.items:
            return None
        last_id = self._last_started_item_id.get(playlist.id)
        if not last_id:
            return 0
        last_index = self._index_of_item(playlist, last_id)
        if last_index is None:
            return 0
        return (last_index + 1) % len(playlist.items)

    @staticmethod
    def _index_of_item(playlist: PlaylistModel, item_id: str | None) -> int | None:
        if not item_id:
            return None
        for idx, entry in enumerate(playlist.items):
            if entry.id == item_id:
                return idx
        return None

    def _play_next_alternate(self) -> bool:
        ordered_ids = [playlist_id for playlist_id in self._layout.state.order if playlist_id in self._playlists]
        if not ordered_ids:
            return False

        page_count = len(ordered_ids)
        start_index = self._current_index % page_count
        rotated_order = [ordered_ids[(start_index + offset) % page_count] for offset in range(page_count)]

        for playlist_id in rotated_order:
            panel = self._playlists.get(playlist_id)
            if panel is None:
                continue
            if self._start_next_from_playlist(panel):
                try:
                    index = ordered_ids.index(playlist_id)
                except ValueError:
                    index = 0
                self._current_index = (index + 1) % page_count
                self._layout.set_current(playlist_id)
                self._update_active_playlist_styles()
                self._announce_event("playlist", f"Aktywna playlista {panel.model.name}")
                return True

        return False

    def _on_global_play_next(self, event: wx.CommandEvent) -> None:
        if not self._playlists:
            self._announce_event("playlist", _("No playlists available"))
            return

        panel, focus = self._active_news_panel()
        if panel:
            if panel.activate_toolbar_control(focus):
                return
            if panel.consume_space_shortcut():
                return
            if panel.is_edit_control(focus):
                return
            return

        if self._alternate_play_next:
            if not self._play_next_alternate():
                self._announce_event("playback_events", _("No scheduled tracks available"))
            return

        panel = self._get_current_music_panel()
        if panel is None:
            self._announce_event("playlist", _("Select a playlist first"))
            return

        # Automix: Play Next zawsze gra kolejny pending w kolejności; break zatrzymuje i wybieramy pending za ostatnim PLAYED.
        if self._auto_mix_enabled and panel.model.kind is PlaylistKind.MUSIC:
            if self._auto_mix_play_next(panel):
                return
            self._announce_event("playback_events", _("No scheduled tracks available"))
            return

        if not self._start_next_from_playlist(panel):
            self._announce_event("playback_events", _("No scheduled tracks available"))

    def _handle_playback_finished(self, playlist_id: str, item_id: str) -> None:
        logger.debug("UI: playback finished callback playlist=%s item=%s", playlist_id, item_id)
        self._playback.auto_mix_state.pop((playlist_id, item_id), None)
        self._clear_mix_plan(playlist_id, item_id)
        context = self._playback.contexts.pop((playlist_id, item_id), None)
        if context:
            try:
                context.player.set_finished_callback(None)
                context.player.set_progress_callback(None)
            except Exception:
                pass
        panel = self._playlists.get(playlist_id)
        if not panel:
            return
        model = panel.model
        item_index = next((idx for idx, track in enumerate(model.items) if track.id == item_id), None)
        if item_index is None:
            return
        item = model.items[item_index]

        removed = False
        previous_selection = panel.get_selected_indices()
        previous_focus = panel.get_focused_index()
        if self._auto_remove_played:
            removed_item = self._remove_item_from_playlist(panel, model, item_index, refocus=True)
            self._announce_event("playback_events", _("Removed played track %s") % removed_item.title)
            removed = True
        else:
            model.mark_played(item_id)
            panel.mark_item_status(item_id, item.status)
            # przywróć wcześniejszą selekcję/focus gdy follow-playing jest wyłączone
            if self._focus_playing_track:
                panel.refresh(focus=False)
            else:
                if previous_selection:
                    panel.refresh(selected_indices=previous_selection, focus=True)
                elif previous_focus != wx.NOT_FOUND and 0 <= previous_focus < len(model.items):
                    panel.refresh(focus=False)
                    panel.select_index(previous_focus, focus=True)
                else:
                    panel.refresh(focus=False)

        if context:
            try:
                context.player.stop()
            except Exception as exc:  # pylint: disable=broad-except
                self._announce_event("playback_errors", _("Player stop error: %s") % exc)
        break_flag = (
            model.kind is PlaylistKind.MUSIC
            and (
                model.break_resume_index is not None
                or item.break_after
                or self._active_break_item.get(playlist_id) == item_id
            )
        )
        logger.debug(
            "UI: finished item=%s break_flag=%s break_after=%s break_resume=%s active_break=%s",
            item_id,
            break_flag,
            item.break_after,
            model.break_resume_index,
            self._active_break_item.get(playlist_id),
        )
        if not removed:
            self._announce_event("playback_events", _("Finished %s") % item.title)

        # wyznacz, gdzie wznowić po breaku (pozycja po tym utworze, z zawijaniem)
        if break_flag:
            if model.items:
                target_index = (item_index + 1) % len(model.items)
            else:
                target_index = None
            model.break_resume_index = target_index
            item.break_after = False
            self._playback.auto_mix_state.pop((playlist_id, item_id), None)
            self._active_break_item.pop(playlist_id, None)
            self._auto_mix_tracker.set_last_started(playlist_id, item_id)
            return
        # bez breaka: aktualizuj kursor automix na kolejny sekwencyjnie
        if self._auto_mix_enabled and model.kind is PlaylistKind.MUSIC and model.items:
            self._auto_mix_tracker.set_last_started(playlist_id, item_id)
            # Jeśli miks nie wystartował (brak aktywnego kontekstu), odpal awaryjnie następny w sekwencji.
            if self._get_playback_context(playlist_id) is None:
                try:
                    self._auto_mix_play_next(panel)
                except Exception:
                    logger.exception("UI: auto fallback after finish failed playlist=%s", playlist_id)

    def _handle_playback_progress(self, playlist_id: str, item_id: str, seconds: float) -> None:
        context_entry = self._playback.contexts.get((playlist_id, item_id))
        if not context_entry:
            return
        panel = self._playlists.get(playlist_id)
        if not panel:
            return
        # automix: ignoruj wczesne wyzwalanie z powodu UI selection – sekwencją zarządza tracker
        if self._auto_mix_enabled and panel.model.kind is PlaylistKind.MUSIC:
            queued_selection = False
        item = next((track for track in panel.model.items if track.id == item_id), None)
        if not item:
            return
        item.update_progress(seconds)
        panel.update_progress(item_id)
        self._maybe_focus_playing_item(panel, item_id)
        self._consider_intro_alert(panel, item, context_entry, seconds)
        self._consider_track_end_alert(panel, item, context_entry)

        queued_selection = self._playlist_has_selection(playlist_id)
        if self._auto_mix_enabled or queued_selection:
            self._auto_mix_state_process(panel, item, context_entry, seconds, queued_selection)

    def _auto_mix_state_process(
        self,
        panel: PlaylistPanel,
        item: PlaylistItem,
        context_entry: PlaybackContext,
        seconds: float,
        queued_selection: bool,
    ) -> None:
        playlist = panel.model
        if playlist.kind is not PlaylistKind.MUSIC:
            return
        if playlist.break_resume_index is not None:
            return
        # jeśli w playliście jest aktywny break, blokuj automix
        if self._active_break_item.get(playlist.id):
            return
        # jeśli ten utwór był oznaczony breakiem, zablokuj miks do czasu zakończenia
        key = (playlist.id, item.id)
        state = self._playback.auto_mix_state.get(key)
        if state == "loop_hold":
            return
        if state == "break_halt":
            return
        if not self._auto_mix_enabled and not queued_selection:
            return
        # Break zatrzymuje automix – nie miksuj w trakcie utworu z breakiem.
        if item.break_after:
            return

        plan = self._mix_plans.get(key)
        native_trigger = plan.native_trigger if plan else self._supports_mix_trigger(context_entry.player)
        mix_at: float | None = None
        fade_seconds = self._fade_duration
        base_cue = item.cue_in_seconds or 0.0
        effective_duration = item.effective_duration_seconds

        if plan:
            mix_at = plan.mix_at
            fade_seconds = plan.fade_seconds
            base_cue = plan.base_cue
            effective_duration = plan.effective_duration
        else:
            mix_at, fade_seconds, base_cue, effective_duration = self._resolve_mix_timing(item)
            self._register_mix_plan(
                playlist.id,
                item.id,
                mix_at=mix_at,
                fade_seconds=fade_seconds,
                base_cue=base_cue,
                effective_duration=effective_duration,
                native_trigger=native_trigger,
            )
            plan = self._mix_plans.get(key)

        release_offset = 0.0
        if plan and plan.triggered:
            return
        if mix_at is not None and native_trigger:
            track_end = base_cue + effective_duration
            headroom_after_mix = max(0.0, track_end - mix_at)
            fade_guard_source = self._fade_duration if item.segue_seconds is not None else fade_seconds
            fade_guard = min(MIX_NATIVE_LATE_GUARD, max(0.0, fade_guard_source))
            guard_window = min(fade_guard, headroom_after_mix)
            late_guard_shortfall = max(0.0, fade_guard - guard_window)
            if late_guard_shortfall > 0.0 and guard_window > 0.0:
                release_offset = min(guard_window, late_guard_shortfall / 2.0)
            if seconds < mix_at - MIX_NATIVE_EARLY_GUARD:
                return
            if seconds < mix_at + guard_window:
                # Nie czekaj na backend kiedy zapasu jest mniej niż oczekiwany guard lub brak zapasu po miksie.
                if late_guard_shortfall <= 0.0 or seconds < mix_at - late_guard_shortfall:
                    return

        already_mixing = self._playback.auto_mix_state.get(key, False)

        elapsed = max(0.0, seconds - base_cue)
        remaining = max(0.0, effective_duration - elapsed)
        mix_remaining: float | None = None
        if mix_at is not None:
            mix_remaining = max(0.0, mix_at - seconds)

        trigger_window = max(fade_seconds, 0.0)
        if item.overlap_seconds:
            trigger_window = max(trigger_window, item.overlap_seconds)
        if item.outro_seconds:
            trigger_window = max(trigger_window, item.outro_seconds)

        remaining_target = mix_remaining if mix_remaining is not None else remaining
        fallback_guard_trigger = False
        if mix_at is not None:
            trigger_threshold = MIX_EXPLICIT_PROGRESS_GUARD
            if native_trigger and release_offset > 0.0:
                trigger_threshold = release_offset
            should_trigger = remaining_target <= trigger_threshold
            if native_trigger and release_offset > 0.0 and remaining_target <= release_offset:
                fallback_guard_trigger = True
        else:
            should_trigger = remaining_target <= max(0.1, trigger_window)
        if not should_trigger or already_mixing:
            return

        if self._playback.auto_mix_state.get(key) in {"break_halt", "loop_hold"}:
            return
        self._playback.auto_mix_state[key] = True
        if plan:
            plan.triggered = True
        ignore_ui_selection = self._auto_mix_enabled and not queued_selection
        started = self._start_next_from_playlist(
            panel,
            ignore_ui_selection=ignore_ui_selection,
            advance_focus=True,
            restart_playing=False,
            force_automix_sequence=self._auto_mix_enabled,
            prefer_overlap=True,
        )
        if started and self._fade_duration > 0.0:
            fade_source = max(0.0, fade_seconds)
            if fallback_guard_trigger:
                # fallback progresowy potrzebuje miękkiego wyciszenia z pełną długością fade'u
                fade_source = max(fade_source, self._fade_duration)
            fade_duration = min(fade_source, remaining)
            logger.debug(
                "UI: automix progress fade duration=%.3f planned=%.3f remaining=%.3f guard=%s current=%.3f",
                fade_duration,
                fade_source,
                remaining,
                fallback_guard_trigger,
                seconds,
            )
            if fade_duration > 0.0:
                try:
                    context_entry.player.fade_out(fade_duration)
                except Exception:
                    pass
        elif plan:
            plan.triggered = False
            self._playback.auto_mix_state.pop(key, None)

    def _auto_mix_now(self, playlist: PlaylistModel, item: PlaylistItem, panel: PlaylistPanel) -> None:
        """Wyzwól miks natychmiast z precyzyjnego punktu (segue/overlap/fade sync z BASS)."""
        key = (playlist.id, item.id)
        plan = self._mix_plans.get(key)
        if plan and plan.triggered:
            return
        queued_selection = self._playlist_has_selection(playlist.id)
        if not self._auto_mix_enabled and not queued_selection:
            return
        if self._playback.auto_mix_state.get(key):
            return
        if item.break_after or self._active_break_item.get(playlist.id) == item.id:
            self._playback.auto_mix_state[(playlist.id, item.id)] = "break_halt"
            logger.debug(
                "UI: auto_mix_now ignored due to break playlist=%s item=%s",
                playlist.id,
                item.id,
            )
            return
        base_cue = plan.base_cue if plan else (item.cue_in_seconds or 0.0)
        length_seconds = None
        ctx = self._playback.contexts.get(key)
        if ctx:
            getter = getattr(ctx.player, "get_length_seconds", None)
            if getter:
                try:
                    length_seconds = float(getter())
                except Exception:
                    length_seconds = None
        if length_seconds is None and plan:
            length_seconds = base_cue + plan.effective_duration
        max_mix_point = None
        if length_seconds and length_seconds > 0.0:
            max_mix_point = max(0.0, length_seconds - 0.01)
        expected_mix = plan.mix_at if plan else self._mix_trigger_points.get(key)
        if expected_mix is None:
            mix_trigger, fade_seconds, base_cue, eff = self._resolve_mix_timing(item)
            native_trigger = self._supports_mix_trigger(ctx.player if ctx else None)
            self._register_mix_plan(
                playlist.id,
                item.id,
                mix_at=mix_trigger,
                fade_seconds=fade_seconds,
                base_cue=base_cue,
                effective_duration=eff,
                native_trigger=native_trigger,
            )
            expected_mix = mix_trigger
            plan = self._mix_plans.get(key)
        if expected_mix is not None and max_mix_point is not None:
            clamped_expected = min(expected_mix, max_mix_point)
            if clamped_expected != expected_mix:
                logger.debug(
                    "UI: clamping mix trigger to track length playlist=%s item=%s expected=%.3f clamped=%.3f",
                    playlist.id,
                    item.id,
                    expected_mix,
                    clamped_expected,
                )
                expected_mix = clamped_expected
                self._register_mix_plan(
                    playlist.id,
                    item.id,
                    mix_at=clamped_expected,
                    fade_seconds=plan.fade_seconds if plan else self._fade_duration,
                    base_cue=base_cue,
                    effective_duration=plan.effective_duration if plan else item.effective_duration_seconds,
                    native_trigger=self._supports_mix_trigger(ctx.player if ctx else None),
                )
                plan = self._mix_plans.get(key)
        if expected_mix is not None:
            current_abs = base_cue + (item.current_position or 0.0)
            tolerance = 0.75
            if expected_mix is not None and current_abs < expected_mix - tolerance:
                effective_override = None
                if length_seconds is not None:
                    effective_override = max(0.0, length_seconds - base_cue)
                rescheduled, _fade, _base_cue, _eff = self._resolve_mix_timing(
                    item,
                    effective_duration_override=effective_override,
                )
                if rescheduled is not None and max_mix_point is not None:
                    rescheduled = min(rescheduled, max_mix_point)
                fallback_mix = rescheduled if rescheduled is not None else expected_mix
                fallback_fade = _fade if rescheduled is not None else (plan.fade_seconds if plan else self._fade_duration)
                fallback_base = _base_cue if rescheduled is not None else base_cue
                fallback_eff = _eff if rescheduled is not None else (plan.effective_duration if plan else item.effective_duration_seconds)
                if self._supports_mix_trigger(ctx.player if ctx else None):
                    try:
                        self._playback.update_mix_trigger(
                            playlist.id,
                            item.id,
                            mix_trigger_seconds=None,
                            on_mix_trigger=None,
                        )
                    except Exception:
                        pass
                self._register_mix_plan(
                    playlist.id,
                    item.id,
                    mix_at=fallback_mix,
                    fade_seconds=fallback_fade,
                    base_cue=fallback_base,
                    effective_duration=fallback_eff,
                    native_trigger=False,
                )
                plan = self._mix_plans.get(key)
                logger.debug(
                    "UI: auto_mix_now backend fired early -> fallback to progress trigger playlist=%s item=%s current=%.3f expected=%.3f",
                    playlist.id,
                    item.id,
                    current_abs,
                    fallback_mix if fallback_mix is not None else -1.0,
                )
                return
        self._playback.auto_mix_state[key] = True
        self._mark_mix_triggered(playlist.id, item.id)
        effective_total = (
            max(0.0, (length_seconds - base_cue))
            if length_seconds is not None
            else (plan.effective_duration if plan else item.effective_duration_seconds)
        )
        remaining = max(0.0, effective_total - item.current_position)
        logger.debug(
            "UI: auto_mix_now fired playlist=%s item=%s current_pos=%.3f remaining=%.3f",
            playlist.id,
            item.id,
            item.current_position,
            remaining,
        )
        started = self._start_next_from_playlist(
            panel,
            ignore_ui_selection=self._auto_mix_enabled and not queued_selection,
            advance_focus=True,
            restart_playing=False,
            force_automix_sequence=self._auto_mix_enabled,
            prefer_overlap=True,
        )
        if started and self._fade_duration > 0.0:
            fade_target = plan.fade_seconds if plan else self._fade_duration
            fade_duration = min(fade_target, remaining)
            logger.debug(
                "UI: auto_mix_now fade duration=%.3f planned=%.3f remaining=%.3f current=%.3f",
                fade_duration,
                fade_target,
                remaining,
                item.current_position,
            )
            ctx = self._playback.contexts.get(key)
            if ctx and fade_duration > 0.0:
                try:
                    ctx.player.fade_out(fade_duration)
                except Exception:
                    pass
        else:
            # jeśli nie udało się wystartować, oczyść flagę, aby fallback mógł spróbować ponownie
            plan_obj = self._mix_plans.get(key)
            if plan_obj:
                plan_obj.triggered = False
            self._playback.auto_mix_state.pop(key, None)

    def _manual_fade_duration(self, playlist: PlaylistModel, item: PlaylistItem | None) -> float:
        fade_seconds = max(0.0, self._fade_duration)
        if item is None:
            return fade_seconds
        plans = getattr(self, "_mix_plans", {}) or {}
        plan = plans.get((playlist.id, item.id))
        effective_duration = None
        if plan:
            fade_seconds = max(0.0, plan.fade_seconds)
            effective_duration = plan.effective_duration
        else:
            effective_override = self._measure_effective_duration(playlist, item)
            _mix_at, resolved_fade, _base_cue, effective_duration = self._resolve_mix_timing(
                item,
                effective_duration_override=effective_override,
            )
            fade_seconds = max(0.0, resolved_fade)
        if effective_duration is None:
            effective_duration = item.effective_duration_seconds
        if effective_duration is not None:
            current_pos = getattr(item, "current_position", 0.0) or 0.0
            current_pos = max(0.0, current_pos)
            remaining = max(0.0, effective_duration - current_pos)
            fade_seconds = min(fade_seconds, remaining)
        return fade_seconds

    def _on_playlist_hotkey(self, event: wx.CommandEvent) -> None:
        action = self._action_by_id.get(event.GetId())
        if not action:
            return

        if action == "mix_points":
            context = self._get_selected_context(kinds=(PlaylistKind.MUSIC, PlaylistKind.FOLDER))
            if context is None:
                return
            _panel, model, indices = context
            index = indices[0]
            if not (0 <= index < len(model.items)):
                self._announce_event("playlist", _("No track selected"))
                return
            item = model.items[index]
            self._on_mix_points_configure(model.id, item.id)
            return

        panel = self._get_current_music_panel()
        if panel is None:
            self._announce_event("playlist", _("Select a playlist first"))
            return

        playlist = panel.model
        if action == "play":
            if self._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC:
                if not self._auto_mix_play_next(panel):
                    self._announce_event("playback_events", _("No scheduled tracks available"))
            else:
                self._start_next_from_playlist(panel)
            return
        if action == "break_toggle":
            if playlist.kind is not PlaylistKind.MUSIC:
                self._announce_event("playlist", _("Breaks are only available on music playlists"))
                return
            indices = panel.get_selected_indices()
            if not indices:
                focus_idx = panel.get_focused_index()
                if focus_idx != wx.NOT_FOUND:
                    indices = [focus_idx]
            if not indices:
                self._announce_event("playlist", _("Select a track to toggle break"))
                return
            last_state = None
            toggled_ids: list[str] = []
            for idx in indices:
                if 0 <= idx < len(playlist.items):
                    track = playlist.items[idx]
                    track.break_after = not track.break_after
                    last_state = track.break_after
                    toggled_ids.append(track.id)
                    if track.break_after:
                        self._playback.auto_mix_state[(playlist.id, track.id)] = "break_halt"
                    else:
                        self._playback.auto_mix_state.pop((playlist.id, track.id), None)
            panel.refresh(indices, focus=True)
            if last_state is not None:
                message = _("Break enabled after track") if last_state else _("Break cleared")
                self._announce_event("playlist", message)
            # zapisz aktywny break dla automix (playlist_id -> item_id); jeśli wyłączamy, usuń wpis
            if last_state and indices:
                self._active_break_item[playlist.id] = playlist.items[indices[0]].id
            elif not last_state:
                self._active_break_item.pop(playlist.id, None)

            context_entry = self._get_playback_context(playlist.id)
            if context_entry:
                key, ctx = context_entry
                if key[1] in toggled_ids:
                    current_item = playlist.get_item(key[1])
                    if current_item:
                        if last_state:
                            self._clear_mix_plan(playlist.id, current_item.id)
                            self._playback.update_mix_trigger(
                                playlist.id,
                                current_item.id,
                                mix_trigger_seconds=None,
                                on_mix_trigger=None,
                            )
                        else:
                            self._apply_mix_trigger_to_playback(
                                playlist_id=playlist.id,
                                item=current_item,
                                panel=panel,
                            )
            return

        context_entry = self._get_playback_context(playlist.id)
        if context_entry is None:
            self._announce_event("playback_events", _("No active playback for this playlist"))
            return

        key, context = context_entry
        logger.debug("UI: hotkey action=%s playlist=%s current_item=%s", action, playlist.id, key[1])
        item = next((track for track in playlist.items if track.id == key[1]), None)

        if action == "pause":
            try:
                context.player.pause()
            except Exception as exc:  # pylint: disable=broad-except
                self._announce_event("playback_errors", _("Pause error: %s") % exc)
                return
            if item:
                item.status = PlaylistItemStatus.PAUSED
                panel.mark_item_status(item.id, item.status)
                panel.refresh()
            self._playback.contexts[key] = context
            self._announce_event("playback_events", f"Playlista {playlist.name} wstrzymana")
        elif action == "stop":
            self._stop_playlist_playback(playlist.id, mark_played=False, fade_duration=0.0)
            self._announce_event("playback_events", f"Playlista {playlist.name} zatrzymana")
            self._set_auto_mix_enabled(False, reason=_("Auto mix disabled (manual stop)"))
        elif action == "fade":
            fade_seconds = self._manual_fade_duration(playlist, item)
            logger.debug(
                "UI: manual fade resolved duration=%.3f playlist=%s item=%s",
                fade_seconds,
                playlist.id,
                getattr(item, "id", None),
            )
            self._stop_playlist_playback(playlist.id, mark_played=True, fade_duration=fade_seconds)
            if item:
                panel.mark_item_status(item.id, item.status)
                panel.refresh()
            self._announce_event(
                "playback_events",
                _("Playlist %s finished track with fade out") % playlist.name,
            )
            self._set_auto_mix_enabled(False, reason=_("Auto mix disabled (manual stop)"))
    def _get_current_playlist_panel(self):
        current_id = self._layout.state.current_id
        if current_id and current_id in self._playlists:
            return self._playlists[current_id]

        for playlist_id in self._layout.state.order:
            panel = self._playlists.get(playlist_id)
            if panel:
                self._layout.set_current(playlist_id)
                self._current_index = self._layout.current_index()
                self._update_active_playlist_styles()
                self._announce_event("playlist", f"{ANNOUNCEMENT_PREFIX}{panel.model.name}")
                return panel
        return None

    def _get_audio_panel(self, kinds: tuple[PlaylistKind, ...]) -> PlaylistPanel | None:
        panel = self._get_current_playlist_panel()
        if isinstance(panel, PlaylistPanel) and panel.model.kind in kinds:
            return panel
        return None

    def _get_current_music_panel(self) -> PlaylistPanel | None:
        return self._get_audio_panel((PlaylistKind.MUSIC,))

    def _handle_focus_click(self, event: wx.MouseEvent, playlist_id: str) -> None:
        self._focus_playlist_panel(playlist_id)
        event.Skip()

    def _on_playlist_focus(self, playlist_id: str) -> None:
        if playlist_id not in self._playlists:
            return
        current_id = self._layout.state.current_id
        if current_id == playlist_id:
            return
        self._layout.set_current(playlist_id)
        self._current_index = self._layout.current_index()
        self._update_active_playlist_styles()
        panel = self._playlists.get(playlist_id)
        if panel:
            self._announce_event("playlist", f"{ANNOUNCEMENT_PREFIX}{panel.model.name}")
            if isinstance(panel, PlaylistPanel) and panel.model.kind is PlaylistKind.MUSIC:
                self._last_music_playlist_id = playlist_id

    def _get_selected_context(
        self,
        *,
        kinds: tuple[PlaylistKind, ...] = (PlaylistKind.MUSIC,),
    ) -> tuple[PlaylistPanel, PlaylistModel, list[int]] | None:
        panel = self._get_audio_panel(kinds)
        if panel is None:
            self._announce_event("playlist", _("Select a playlist first"))
            return None
        indices = panel.get_selected_indices()
        if not indices:
            if panel.model.items:
                indices = [0]
                panel.set_selection(indices)
            else:
                self._announce_event("playlist", _("Playlist is empty"))
                return None
        return panel, panel.model, sorted(indices)

    def _get_selected_items(
        self,
        *,
        kinds: tuple[PlaylistKind, ...] = (PlaylistKind.MUSIC,),
    ) -> tuple[PlaylistPanel, PlaylistModel, list[tuple[int, PlaylistItem]]] | None:
        context = self._get_selected_context(kinds=kinds)
        if context is None:
            return None
        panel, model, indices = context
        selected: list[tuple[int, PlaylistItem]] = []
        for index in indices:
            if 0 <= index < len(model.items):
                selected.append((index, model.items[index]))
        if not selected:
            self._announce_event("playlist", _("No tracks selected"))
            return None
        return panel, model, selected

    def _serialize_items(self, items: List[PlaylistItem]) -> List[Dict[str, Any]]:
        serialized: List[Dict[str, Any]] = []
        for item in items:
            serialized.append(
                {
                    "path": str(item.path),
                    "title": item.title,
                    "artist": item.artist,
                    "duration": item.duration_seconds,
                    "replay_gain_db": item.replay_gain_db,
                    "cue_in": item.cue_in_seconds,
                    "segue": item.segue_seconds,
                    "segue_fade": item.segue_fade_seconds,
                    "overlap": item.overlap_seconds,
                    "intro": item.intro_seconds,
                    "outro": item.outro_seconds,
                    "loop_start": item.loop_start_seconds,
                    "loop_end": item.loop_end_seconds,
                    "loop_auto_enabled": item.loop_auto_enabled,
                    "loop_enabled": item.loop_enabled,
                }
            )
        return serialized

    def _create_item_from_serialized(self, data: Dict[str, Any]) -> PlaylistItem:
        path = Path(data["path"])
        loop_auto_enabled = bool(data.get("loop_auto_enabled"))
        loop_enabled = bool(data.get("loop_enabled")) or loop_auto_enabled
        item = self._playlist_factory.create_item(
            path=path,
            title=data.get("title", path.stem),
            artist=data.get("artist"),
            duration_seconds=float(data.get("duration", 0.0)),
            replay_gain_db=data.get("replay_gain_db"),
            cue_in_seconds=data.get("cue_in"),
            segue_seconds=data.get("segue"),
            segue_fade_seconds=data.get("segue_fade"),
            overlap_seconds=data.get("overlap"),
            intro_seconds=data.get("intro"),
            outro_seconds=data.get("outro"),
            loop_start_seconds=data.get("loop_start"),
            loop_end_seconds=data.get("loop_end"),
            loop_auto_enabled=loop_auto_enabled,
            loop_enabled=loop_enabled,
        )
        return item

    def _refresh_playlist_view(self, panel: PlaylistPanel, selection: list[int] | None) -> None:
        if selection is None:
            panel.refresh()
        else:
            panel.refresh(selection)
        panel.focus_list()

    def _get_system_clipboard_paths(self) -> list[Path]:
        paths: list[Path] = []
        clipboard = wx.TheClipboard
        if not clipboard.Open():
            return paths
        try:
            data = wx.FileDataObject()
            if clipboard.GetData(data):
                paths = [Path(filename) for filename in data.GetFilenames()]
        finally:
            clipboard.Close()
        return paths

    def _set_system_clipboard_paths(self, paths: list[Path]) -> None:
        clipboard = wx.TheClipboard
        if not clipboard.Open():
            return
        try:
            data = wx.FileDataObject()
            added = False
            for path in paths:
                try:
                    data.AddFile(str(path))
                    added = True
                except Exception:
                    continue
            if added:
                clipboard.SetData(data)
        finally:
            clipboard.Close()

    def _collect_files_from_paths(self, paths: list[Path]) -> tuple[list[Path], int]:
        files: list[Path] = []
        skipped = 0
        for path in paths:
            if path.is_file():
                if is_supported_audio_file(path):
                    files.append(path)
                else:
                    skipped += 1
                continue
            if path.is_dir():
                try:
                    for file_path in sorted(path.rglob("*")):
                        if file_path.is_file():
                            if is_supported_audio_file(file_path):
                                files.append(file_path)
                            else:
                                skipped += 1
                except Exception as exc:
                    logger.warning("Failed to enumerate %s: %s", path, exc)
        return files, skipped

    def _metadata_worker_count(self, total: int) -> int:
        if total <= 1:
            return 1
        cpu = os.cpu_count() or 4
        return max(1, min(cpu, 8, total))

    def _build_playlist_item(
        self,
        path: Path,
        metadata: AudioMetadata,
        *,
        override_title: str | None = None,
        override_artist: str | None = None,
        override_duration: float | None = None,
    ) -> PlaylistItem:
        title = override_title or metadata.title or path.stem
        artist = override_artist or metadata.artist
        duration = override_duration if override_duration is not None else metadata.duration_seconds
        return self._playlist_factory.create_item(
            path=path,
            title=title,
            artist=artist,
            duration_seconds=duration,
            replay_gain_db=metadata.replay_gain_db,
            cue_in_seconds=metadata.cue_in_seconds,
            segue_seconds=metadata.segue_seconds,
            segue_fade_seconds=metadata.segue_fade_seconds,
            overlap_seconds=metadata.overlap_seconds,
            intro_seconds=metadata.intro_seconds,
            outro_seconds=metadata.outro_seconds,
            loop_start_seconds=metadata.loop_start_seconds,
            loop_end_seconds=metadata.loop_end_seconds,
            loop_auto_enabled=metadata.loop_auto_enabled,
            loop_enabled=metadata.loop_enabled,
        )

    def _load_playlist_item(
        self,
        path: Path,
        entry: dict[str, Any] | None = None,
    ) -> PlaylistItem | None:
        if not path.exists():
            logger.warning("Playlist entry %s does not exist", path)
            return None
        try:
            metadata: AudioMetadata = extract_metadata(path)
        except Exception as exc:  # pylint: disable=broad-except
            if entry is None:
                logger.warning("Failed to read metadata from %s: %s", path, exc)
                return None
            logger.warning("Using fallback metadata for %s: %s", path, exc)
            metadata = AudioMetadata(
                title=entry.get("title") or path.stem,
                duration_seconds=float(entry.get("duration") or 0.0),
                artist=entry.get("artist"),
            )
        override_title = entry.get("title") if entry else None
        override_artist = entry.get("artist") if entry else None
        override_duration = None
        if entry:
            duration = entry.get("duration")
            if duration is not None:
                override_duration = float(duration or 0.0)
        return self._build_playlist_item(
            path,
            metadata,
            override_title=override_title,
            override_artist=override_artist,
            override_duration=override_duration,
        )

    def _create_items_from_paths(self, file_paths: list[Path]) -> list[PlaylistItem]:
        sources = [(path, None) for path in file_paths]
        return self._load_items_from_sources(sources)

    def _run_item_loader(
        self,
        *,
        description: str,
        worker: Callable[[], list[PlaylistItem]],
        on_complete: Callable[[list[PlaylistItem]], None],
    ) -> None:
        busy = wx.BusyInfo(description, parent=self)
        holder: dict[str, wx.BusyInfo | None] = {"busy": busy}

        def task() -> None:
            try:
                result = worker()
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Failed to load playlist items: %s", exc)
                result = []

            def finish() -> None:
                busy_obj = holder.pop("busy", None)
                if busy_obj is not None:
                    del busy_obj
                on_complete(result)

            wx.CallAfter(finish)

        Thread(target=task, daemon=True).start()

    def _create_items_from_m3u_entries(self, entries: list[dict[str, Any]]) -> list[PlaylistItem]:
        sources = []
        for entry in entries:
            audio_path = Path(entry["path"])
            sources.append((audio_path, entry))
        return self._load_items_from_sources(sources)

    def _load_items_from_sources(
        self,
        sources: list[tuple[Path, dict[str, Any] | None]],
    ) -> list[PlaylistItem]:
        if not sources:
            return []
        worker_count = self._metadata_worker_count(len(sources))
        if worker_count <= 1:
            items = [self._load_playlist_item(path, entry) for path, entry in sources]
        else:
            paths, entries = zip(*sources)
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                items = list(executor.map(self._load_playlist_item, paths, entries))
        return [item for item in items if item is not None]

    def _finalize_import_playlist(self, panel: PlaylistPanel, new_items: list[PlaylistItem], filename: str) -> None:
        playlist_id = panel.model.id
        if playlist_id not in self._playlists or self._playlists.get(playlist_id) is not panel:
            return
        if not new_items:
            self._announce_event("import_export", _("Playlist file did not contain supported tracks"))
            return
        panel.model.add_items(new_items)
        panel.refresh()
        self._announce_event(
            "import_export",
            _("Imported %d items from %s") % (len(new_items), filename),
        )

    def _maybe_focus_playing_item(self, panel: PlaylistPanel, item_id: str) -> None:
        if not self._focus_playing_track:
            return
        playlist_id = panel.model.id
        if self._focus_lock.get(playlist_id):
            current = panel.get_selected_indices()
            if len(current) == 1:
                selected_index = current[0]
                if 0 <= selected_index < len(panel.model.items):
                    if panel.model.items[selected_index].id == item_id:
                        self._focus_lock[playlist_id] = False
                    else:
                        return
            else:
                return
        else:
            current = panel.get_selected_indices()
            if len(current) == 1:
                selected_index = current[0]
                if 0 <= selected_index < len(panel.model.items):
                    if panel.model.items[selected_index].id == item_id:
                        return
        for index, track in enumerate(panel.model.items):
            if track.id == item_id:
                panel.select_index(index)
                self._focus_lock[playlist_id] = False
                break

    def _resolve_remaining_playback(self) -> tuple[PlaylistModel, PlaylistItem, float] | None:
        candidate_ids: list[str] = []
        panel = self._get_current_music_panel()
        if panel:
            candidate_ids.append(panel.model.id)
        for playlist_id, _item_id in self._playback.contexts.keys():
            if playlist_id not in candidate_ids:
                candidate_ids.append(playlist_id)
        for playlist_id in candidate_ids:
            panel = self._playlists.get(playlist_id)
            if not isinstance(panel, PlaylistPanel):
                continue
            item = self._active_playlist_item(panel.model)
            if item is None:
                continue
            remaining = max(0.0, item.effective_duration_seconds - item.current_position)
            return panel.model, item, remaining
        return None

    def _active_playlist_item(self, playlist: PlaylistModel) -> PlaylistItem | None:
        playlist_keys = [key for key in self._playback.contexts.keys() if key[0] == playlist.id]
        if not playlist_keys:
            return None
        last_started = self._last_started_item_id.get(playlist.id)
        if last_started:
            candidate_key = (playlist.id, last_started)
            if candidate_key in self._playback.contexts:
                item = playlist.get_item(last_started)
                if item:
                    return item
        for key in reversed(list(playlist_keys)):
            item = playlist.get_item(key[1])
            if item:
                return item
        return None

    def _compute_intro_remaining(self, item: PlaylistItem, absolute_seconds: float | None = None) -> float | None:
        intro = item.intro_seconds
        if intro is None:
            return None
        if absolute_seconds is None:
            absolute = (item.cue_in_seconds or 0.0) + item.current_position
        else:
            absolute = absolute_seconds
        remaining = intro - absolute
        if remaining <= 0:
            return 0.0
        return remaining

    def _announce_intro_remaining(self, remaining: float, *, prefix_only: bool = False) -> None:
        seconds = max(0.0, remaining)
        if prefix_only:
            message = f"{seconds:.0f} seconds"
        else:
            message = _("Intro remaining: {seconds:.0f} seconds").format(seconds=seconds)
        self._announce_event("intro_alert", message)

    def _announce_track_end_remaining(self, remaining: float) -> None:
        seconds = max(0.0, remaining)
        message = _("Track ending in {seconds:.0f} seconds").format(seconds=seconds)
        self._announce_event("track_end_alert", message)

    def _cleanup_intro_alert_player(self, player: Player) -> None:
        for idx, (stored_player, temp_path) in enumerate(list(self._intro_alert_players)):
            if stored_player is player:
                try:
                    stored_player.stop()
                except Exception:  # pylint: disable=broad-except
                    pass
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:  # pylint: disable=broad-except
                    pass
                self._intro_alert_players.pop(idx)
                break

    def _play_intro_alert(self) -> bool:
        if self._intro_alert_seconds <= 0:
            return False
        if not self._settings.get_announcement_enabled("intro_alert"):
            return False
        pfl_device_id = self._playback.pfl_device_id or self._settings.get_pfl_device()
        if not pfl_device_id:
            return False
        if self._playback.preview_context:
            return False
        known_devices = {device.id for device in self._audio_engine.get_devices()}
        if pfl_device_id not in known_devices:
            self._audio_engine.refresh_devices()
            known_devices = {device.id for device in self._audio_engine.get_devices()}
        if pfl_device_id not in known_devices:
            return False
        try:
            player = self._audio_engine.create_player(pfl_device_id)
        except Exception:  # pylint: disable=broad-except
            return False

        try:
            resource = files("sara.audio.media").joinpath("beep.wav")
            with resource.open("rb") as source:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
                tmp.write(source.read())
                tmp_path = Path(tmp.name)
        except Exception:  # pylint: disable=broad-except
            try:
                player.stop()
            except Exception:  # pylint: disable=broad-except
                pass
            if 'tmp' in locals():
                tmp.close()
            return False
        else:
            tmp.close()

        try:
            player.set_finished_callback(lambda _item_id: wx.CallAfter(self._cleanup_intro_alert_player, player))
            player.set_progress_callback(None)
            player.play("intro-alert", str(tmp_path), allow_loop=False)
        except Exception:  # pylint: disable=broad-except
            try:
                player.stop()
            except Exception:  # pylint: disable=broad-except
                pass
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:  # pylint: disable=broad-except
                pass
            return False

        self._intro_alert_players.append((player, tmp_path))
        return True

    def _cleanup_track_end_alert_player(self, player: Player) -> None:
        for idx, (stored_player, temp_path) in enumerate(list(self._track_end_alert_players)):
            if stored_player is player:
                try:
                    stored_player.stop()
                except Exception:  # pylint: disable=broad-except
                    pass
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:  # pylint: disable=broad-except
                    pass
                self._track_end_alert_players.pop(idx)
                break

    def _play_track_end_alert(self) -> bool:
        if self._track_end_alert_seconds <= 0:
            return False
        if not self._settings.get_announcement_enabled("track_end_alert"):
            return False
        pfl_device_id = self._playback.pfl_device_id or self._settings.get_pfl_device()
        if not pfl_device_id:
            return False
        if self._playback.preview_context:
            return False
        known_devices = {device.id for device in self._audio_engine.get_devices()}
        if pfl_device_id not in known_devices:
            self._audio_engine.refresh_devices()
            known_devices = {device.id for device in self._audio_engine.get_devices()}
        if pfl_device_id not in known_devices:
            return False
        try:
            player = self._audio_engine.create_player(pfl_device_id)
        except Exception:  # pylint: disable=broad-except
            return False

        try:
            resource = files("sara.audio.media").joinpath("track_end_alert.wav")
            with resource.open("rb") as source:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
                tmp.write(source.read())
                tmp_path = Path(tmp.name)
        except Exception:  # pylint: disable=broad-except
            try:
                player.stop()
            except Exception:  # pylint: disable=broad-except
                pass
            if 'tmp' in locals():
                tmp.close()
            return False
        else:
            tmp.close()

        try:
            player.set_finished_callback(lambda _item_id: wx.CallAfter(self._cleanup_track_end_alert_player, player))
            player.set_progress_callback(None)
            player.play("track-end-alert", str(tmp_path), allow_loop=False)
        except Exception:  # pylint: disable=broad-except
            try:
                player.stop()
            except Exception:  # pylint: disable=broad-except
                pass
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:  # pylint: disable=broad-except
                pass
            return False

        self._track_end_alert_players.append((player, tmp_path))
        return True

    def _consider_intro_alert(
        self,
        panel: PlaylistPanel,
        item: PlaylistItem,
        context: PlaybackContext,
        absolute_seconds: float,
    ) -> None:
        intro_end = context.intro_seconds if context.intro_seconds is not None else item.intro_seconds
        if intro_end is None:
            return
        # jeśli pętla jest aktywna, pomiń alarm intro (bo intro się nie skończy)
        if item.loop_enabled:
            return
        if context.intro_alert_triggered:
            return
        threshold = self._intro_alert_seconds
        if threshold <= 0:
            return
        remaining = intro_end - absolute_seconds
        if remaining <= 0:
            context.intro_alert_triggered = True
            return
        if remaining <= threshold:
            played = self._play_intro_alert()
            if not played:
                self._announce_intro_remaining(remaining)
            context.intro_alert_triggered = True

    def _consider_track_end_alert(
        self,
        _panel: PlaylistPanel,
        item: PlaylistItem,
        context: PlaybackContext,
    ) -> None:
        if context.track_end_alert_triggered:
            return
        if item.loop_enabled:
            return
        threshold = self._track_end_alert_seconds
        if threshold <= 0:
            return
        duration = item.effective_duration_seconds
        if duration <= 0:
            context.track_end_alert_triggered = True
            return
        if duration < threshold:
            context.track_end_alert_triggered = True
            return
        remaining = duration - item.current_position
        if remaining <= 0:
            context.track_end_alert_triggered = True
            return
        if remaining <= threshold:
            played = self._play_track_end_alert()
            if not played:
                self._announce_track_end_remaining(remaining)
            context.track_end_alert_triggered = True

    def _remove_item_from_playlist(
        self, panel: PlaylistPanel, model: PlaylistModel, index: int, *, refocus: bool = True
    ) -> PlaylistItem:
        item = model.items.pop(index)
        if model.break_resume_index is not None:
            if index < model.break_resume_index:
                model.break_resume_index = max(0, model.break_resume_index - 1)
            elif index == model.break_resume_index and model.break_resume_index >= len(model.items):
                model.break_resume_index = None
        was_selected = item.is_selected
        item.is_selected = was_selected
        self._forget_last_started_item(model.id, item.id)
        if any(key == (model.id, item.id) for key in self._playback.contexts):
            self._stop_playlist_playback(model.id, mark_played=False, fade_duration=0.0)
        if refocus:
            if model.items:
                next_index = min(index, len(model.items) - 1)
                self._refresh_playlist_view(panel, [next_index])
            else:
                self._refresh_playlist_view(panel, None)
        return item

    def _remove_items(
        self, panel: PlaylistPanel, model: PlaylistModel, indices: list[int]
    ) -> list[PlaylistItem]:
        if not indices:
            return []
        removed: list[PlaylistItem] = []
        for index in sorted(indices, reverse=True):
            removed.append(self._remove_item_from_playlist(panel, model, index, refocus=False))
        removed.reverse()
        if model.items:
            next_index = min(indices[0], len(model.items) - 1)
            self._refresh_playlist_view(panel, [next_index])
        else:
            self._refresh_playlist_view(panel, None)
        return removed

    def _forget_last_started_item(self, playlist_id: str, item_id: str) -> None:
        if self._last_started_item_id.get(playlist_id) == item_id:
            self._last_started_item_id[playlist_id] = None

    def _push_undo_action(self, model: PlaylistModel, operation) -> None:
        self._undo_manager.push(UndoAction(model.id, operation))

    def _apply_undo_callback(self, action: UndoAction, reverse: bool) -> bool:
        model = self._get_playlist_model(action.playlist_id)
        panel = self._playlists.get(action.playlist_id)
        if model is None or panel is None:
            return False
        if self._layout.state.current_id != action.playlist_id:
            self._layout.set_current(action.playlist_id)
            self._update_active_playlist_styles()
        try:
            indices = action.revert(model) if reverse else action.apply(model)
        except ValueError as exc:
            logger.error("Undo operation failed: %s", exc)
            return False
        selection = indices if indices else []
        self._refresh_playlist_view(panel, selection)
        return True

    def _announce_operation(self, operation, *, undo: bool) -> None:
        if isinstance(operation, InsertOperation):
            message = _("Undo paste") if undo else _("Redo paste")
        elif isinstance(operation, RemoveOperation):
            message = _("Undo delete") if undo else _("Redo delete")
        elif isinstance(operation, MoveOperation):
            message = _("Undo move") if undo else _("Redo move")
        else:
            message = _("Undo operation") if undo else _("Redo operation")
        self._announce_event("undo_redo", message)

    def _on_copy_selection(self, _event: wx.CommandEvent) -> None:
        context = self._get_selected_items(kinds=(PlaylistKind.MUSIC, PlaylistKind.FOLDER))
        if context is None:
            return
        panel, model, selected = context
        items = [item for _, item in selected]
        self._clipboard.set(self._serialize_items(items))
        existing_paths = [item.path for item in items if item.path.exists()]
        if existing_paths:
            self._set_system_clipboard_paths(existing_paths)
        count = len(items)
        noun = _("track") if count == 1 else _("tracks")
        self._announce_event(
            "clipboard",
            _("Copied %d %s from playlist %s") % (count, noun, model.name),
        )
        panel.focus_list()

    def _on_cut_selection(self, _event: wx.CommandEvent) -> None:
        context = self._get_selected_items()
        if context is None:
            return
        panel, model, selected = context
        items = [item for _, item in selected]
        self._clipboard.set(self._serialize_items(items))
        existing_paths = [item.path for item in items if item.path.exists()]
        if existing_paths:
            self._set_system_clipboard_paths(existing_paths)
        indices = sorted(index for index, _ in selected)
        removed_items = self._remove_items(panel, model, indices)
        count = len(items)
        noun = _("track") if count == 1 else _("tracks")
        self._announce_event("clipboard", _("Cut %d %s") % (count, noun))
        if removed_items:
            operation = RemoveOperation(indices=list(indices), items=list(removed_items))
            self._push_undo_action(model, operation)

    def _on_paste_selection(self, _event: wx.CommandEvent) -> None:
        context = self._get_selected_context()
        panel: PlaylistPanel
        if context is None:
            panel = self._get_current_music_panel()
            if panel is None:
                return
            model = panel.model
            indices: list[int] = []
        else:
            panel, model, indices = context
        index = indices[-1] if indices else None
        insert_at = index + 1 if index is not None else len(model.items)

        clipboard_paths = self._get_system_clipboard_paths()
        if clipboard_paths:
            file_paths, skipped = self._collect_files_from_paths(clipboard_paths)
            if not file_paths:
                if skipped:
                    self._announce_event("clipboard", _("Clipboard does not contain supported audio files"))
                else:
                    self._announce_event("clipboard", _("Clipboard does not contain files or folders"))
                return

            description = _("Loading tracks from clipboard…")
            self._run_item_loader(
                description=description,
                worker=lambda file_paths=file_paths: self._create_items_from_paths(file_paths),
                on_complete=lambda items, panel=panel, model=model, insert_at=insert_at, anchor=index, skipped=skipped: self._finalize_clipboard_paste(
                    panel,
                    model,
                    items,
                    insert_at,
                    anchor,
                    skipped_files=skipped,
                ),
            )
            return

        if not self._clipboard.is_empty():
            new_items = [self._create_item_from_serialized(data) for data in self._clipboard.get()]
            self._finalize_clipboard_paste(panel, model, new_items, insert_at, index, skipped_files=0)
            return

        self._announce_event("clipboard", _("Clipboard is empty"))
        return

    def _finalize_clipboard_paste(
        self,
        panel: PlaylistPanel,
        model: PlaylistModel,
        items: list[PlaylistItem],
        insert_at: int,
        anchor_index: int | None,
        *,
        skipped_files: int,
    ) -> None:
        playlist_id = panel.model.id
        if playlist_id not in self._playlists or self._playlists.get(playlist_id) is not panel:
            return
        if not items:
            selection = [anchor_index] if anchor_index is not None and anchor_index < len(model.items) else None
            self._refresh_playlist_view(panel, selection)
            self._announce_event("clipboard", _("No supported audio files found on the clipboard"))
            return

        insert_at = max(0, min(insert_at, len(model.items)))
        model.items[insert_at:insert_at] = items
        insert_indices = list(range(insert_at, insert_at + len(items)))
        self._refresh_playlist_view(panel, insert_indices)
        count = len(items)
        noun = _("track") if count == 1 else _("tracks")
        self._announce_event("clipboard", _("Pasted %d %s") % (count, noun))
        operation = InsertOperation(indices=list(insert_indices), items=list(items))
        self._push_undo_action(model, operation)
        if skipped_files:
            noun = _("file") if skipped_files == 1 else _("files")
            self._announce_event("clipboard", _("Skipped %d unsupported %s") % (skipped_files, noun))

        return

    def _on_delete_selection(self, _event: wx.CommandEvent) -> None:
        context = self._get_selected_items()
        if context is None:
            return
        panel, model, selected = context
        items = [item for _, item in selected]
        indices = sorted(index for index, _ in selected)
        removed_items = self._remove_items(panel, model, indices)
        count = len(items)
        noun = _("track") if count == 1 else _("tracks")
        self._announce_event("clipboard", _("Deleted %d %s") % (count, noun))
        if removed_items:
            operation = RemoveOperation(indices=list(indices), items=list(removed_items))
            self._push_undo_action(model, operation)

    def _move_selection(self, delta: int) -> None:
        context = self._get_selected_items()
        if context is None:
            return
        panel, model, selected = context
        indices = [index for index, _item in selected]
        operation = MoveOperation(original_indices=list(indices), delta=delta)
        try:
            new_indices = operation.apply(model)
        except ValueError:
            direction = _("up") if delta < 0 else _("down")
            self._announce_event("clipboard", _("Cannot move further %s") % direction)
            return

        self._refresh_playlist_view(panel, new_indices)
        self._push_undo_action(model, operation)
        count = len(selected)
        if count == 1:
            self._announce_event("clipboard", _("Moved %s") % selected[0][1].title)
        else:
            noun = _("track") if count == 1 else _("tracks")
            self._announce_event("clipboard", _("Moved %d %s") % (count, noun))

    def _on_move_selection_up(self, _event: wx.CommandEvent) -> None:
        self._move_selection(-1)

    def _on_move_selection_down(self, _event: wx.CommandEvent) -> None:
        self._move_selection(1)

    def _on_undo(self, _event: wx.CommandEvent) -> None:
        if not self._undo_manager.undo():
            self._announce_event("undo_redo", _("Nothing to undo"))
            return
        self._announce_event("undo_redo", _("Undo operation"))

    def _on_redo(self, _event: wx.CommandEvent) -> None:
        if not self._undo_manager.redo():
            self._announce_event("undo_redo", _("Nothing to redo"))
            return
        self._announce_event("undo_redo", _("Redo operation"))

    def _update_active_playlist_styles(self) -> None:
        active_colour = wx.Colour(230, 240, 255)
        inactive_colour = self._playlist_container.GetBackgroundColour()
        active_text_colour = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
        inactive_text_colour = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)

        current_id = self._layout.state.current_id
        for playlist_id, wrapper in self._playlist_wrappers.items():
            is_active = playlist_id == current_id
            wrapper.SetBackgroundColour(active_colour if is_active else inactive_colour)
            wrapper.Refresh()
            panel = self._playlists.get(playlist_id)
            if panel:
                panel.set_active(is_active)

        for playlist_id, header in self._playlist_headers.items():
            is_active = playlist_id == current_id
            base_title = self._playlist_titles.get(playlist_id, header.GetLabel())
            if header.GetLabel() != base_title:
                header.SetLabel(base_title)
            header.SetForegroundColour(active_text_colour if is_active else inactive_text_colour)
            header.Refresh()

        self._playlist_container.Refresh()

    def _get_playback_context(self, playlist_id: str) -> tuple[tuple[str, str], PlaybackContext] | None:
        return self._playback.get_context(playlist_id)

    def _get_playing_item_id(self, playlist_id: str) -> str | None:
        context = self._get_playback_context(playlist_id)
        if context is None:
            return None
        key, _ctx = context
        return key[1]

    def _get_busy_device_ids(self) -> set[str]:
        return self._playback.get_busy_device_ids()

    def _refresh_selection_display(self, playlist_id: str) -> None:
        panel = self._playlists.get(playlist_id)
        if panel:
            panel.refresh()

    def _stop_playlist_playback(
        self,
        playlist_id: str,
        *,
        mark_played: bool,
        fade_duration: float = 0.0,
    ) -> None:
        removed_contexts = self._playback.stop_playlist(playlist_id, fade_duration=fade_duration)
        panel = self._playlists.get(playlist_id)
        if not panel:
            return
        model = panel.model
        for key, _context in removed_contexts:
            self._clear_mix_plan(key[0], key[1])
            item_index = next((idx for idx, track in enumerate(model.items) if track.id == key[1]), None)
            item = model.items[item_index] if item_index is not None else None
            if not item:
                continue
            if mark_played:
                if item.break_after and model.kind is PlaylistKind.MUSIC:
                    target_index = (item_index + 1) if item_index is not None else None
                    if target_index is not None and target_index >= len(model.items):
                        target_index = None
                    model.break_resume_index = target_index
                    item.break_after = False
                item.status = PlaylistItemStatus.PLAYED
                item.current_position = item.duration_seconds
            else:
                item.status = PlaylistItemStatus.PENDING
                item.current_position = 0.0
            panel.mark_item_status(item.id, item.status)
            panel.update_progress(item.id)
            panel.refresh()

    def _cancel_active_playback(self, playlist_id: str, mark_played: bool = False) -> None:
        self._stop_playlist_playback(playlist_id, mark_played=mark_played, fade_duration=0.0)

    def _announce_event(
        self,
        category: str,
        message: str,
        *,
        spoken_message: str | None = None,
    ) -> None:
        """Announce `message` and optionally override spoken content."""
        self._announcer.announce(category, message, spoken_message=spoken_message)

    def _silence_screen_reader(self) -> None:
        self._announcer.silence()

    def _announce(self, message: str) -> None:
        self._announce_event("general", message)

    def _supports_mix_trigger(self, player: Player | None) -> bool:
        if player is None:
            return False
        try:
            return self._playback.supports_mix_trigger(player)
        except Exception:
            return False

    def _register_mix_plan(
        self,
        playlist_id: str,
        item_id: str,
        *,
        mix_at: float | None,
        fade_seconds: float,
        base_cue: float,
        effective_duration: float,
        native_trigger: bool,
    ) -> None:
        key = (playlist_id, item_id)
        if mix_at is None:
            self._clear_mix_plan(playlist_id, item_id)
            return
        self._mix_plans[key] = MixPlan(
            mix_at=mix_at,
            fade_seconds=fade_seconds,
            base_cue=base_cue,
            effective_duration=effective_duration,
            native_trigger=native_trigger,
            triggered=False,
        )
        self._mix_trigger_points[key] = mix_at

    def _clear_mix_plan(self, playlist_id: str, item_id: str) -> None:
        key = (playlist_id, item_id)
        self._mix_plans.pop(key, None)
        self._mix_trigger_points.pop(key, None)

    def _mark_mix_triggered(self, playlist_id: str, item_id: str) -> None:
        plan = self._mix_plans.get((playlist_id, item_id))
        if plan:
            plan.triggered = True

    def _resolve_mix_timing(
        self,
        item: PlaylistItem,
        overrides: dict[str, float | None] | None = None,
        *,
        effective_duration_override: float | None = None,
    ) -> tuple[float | None, float, float, float]:
        """Return (mix_at_seconds, fade_seconds, base_cue, effective_duration) using optional overrides."""
        overrides = dict(overrides or {})
        preview_pre_seconds = overrides.pop("_preview_pre_seconds", None)
        base_cue = overrides.get("cue")
        base_cue = base_cue if base_cue is not None else (item.cue_in_seconds or 0.0)
        effective_duration = (
            max(0.0, effective_duration_override)
            if effective_duration_override is not None
            else max(0.0, (item.duration_seconds or 0.0) - base_cue)
        )

        segue_val = overrides.get("segue")
        segue_val = segue_val if segue_val is not None else item.segue_seconds
        overlap_val = overrides.get("overlap")
        overlap_val = overlap_val if overlap_val is not None else item.overlap_seconds
        overlap_val = max(0.0, overlap_val) if overlap_val is not None else None
        segue_fade_val = overrides.get("segue_fade")
        segue_fade_val = segue_fade_val if segue_fade_val is not None else getattr(item, "segue_fade_seconds", None)
        segue_fade_val = max(0.0, segue_fade_val) if segue_fade_val is not None else None

        mix_at = None
        fade_seconds = self._fade_duration
        if segue_val is not None:
            mix_at = base_cue + max(0.0, segue_val)
            if segue_fade_val is not None:
                fade_seconds = segue_fade_val
        elif overlap_val is not None:
            mix_at = base_cue + max(0.0, effective_duration - overlap_val)
            fade_seconds = overlap_val
        elif self._fade_duration > 0.0:
            mix_at = base_cue + max(0.0, effective_duration - self._fade_duration)
            fade_seconds = self._fade_duration

        if mix_at is not None:
            # nigdy nie przekraczaj realnej długości ścieżki – klamruj z lekkim marginesem
            cap_target = base_cue + max(0.0, effective_duration - 0.01)
            if mix_at > cap_target:
                mix_at = cap_target
            # dostosuj fade do dostępnego fragmentu
            remaining_after_mix = max(0.0, base_cue + effective_duration - mix_at)
            fade_seconds = min(fade_seconds, remaining_after_mix)
        return mix_at, fade_seconds, base_cue, effective_duration

    def _measure_effective_duration(self, playlist: PlaylistModel, item: PlaylistItem) -> float | None:
        contexts = getattr(self._playback, "contexts", None)
        if isinstance(contexts, dict):
            context = contexts.get((playlist.id, item.id))
            if context:
                getter = getattr(context.player, "get_length_seconds", None)
                if getter:
                    try:
                        length_seconds = float(getter())
                    except Exception:
                        length_seconds = None
                    else:
                        if length_seconds and length_seconds > 0:
                            cue = item.cue_in_seconds or 0.0
                            return max(0.0, length_seconds - cue)
        try:
            from sara.audio.bass import BassManager  # type: ignore
        except Exception:
            return None
        stream = 0
        manager = None
        try:
            manager = BassManager.instance()
            manager.ensure_device(0)
            stream = manager.stream_create_file(0, item.path, decode=True, set_device=True)
            length_seconds = manager.channel_get_length_seconds(stream)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Failed to probe track length via BASS for %s: %s", item.path, exc)
            return None
        finally:
            if stream and manager:
                try:
                    manager.stream_free(stream)
                except Exception:
                    pass
        if not length_seconds or length_seconds <= 0:
            return None
        cue = item.cue_in_seconds or 0.0
        return max(0.0, length_seconds - cue)

    def _compute_mix_trigger_seconds(self, item: PlaylistItem) -> float | None:
        """Calculate absolute time (seconds) to trigger automix/crossfade."""
        mix_at, _, _, _ = self._resolve_mix_timing(item)
        return mix_at

    def _preview_mix_with_next(
        self,
        playlist: PlaylistModel,
        item: PlaylistItem,
        *,
        overrides: dict[str, Optional[float]] | None = None,
    ) -> bool:
        """Start a short PFL preview of the mix with the next track."""
        if len(playlist.items) < 2:
            self._announce_event("pfl", _("No next track to mix"))
            return False
        idx = self._index_of_item(playlist, item.id)
        if idx is None:
            self._announce_event("pfl", _("No next track to mix"))
            return False
        next_idx = (idx + 1) % len(playlist.items)
        if next_idx == idx:
            self._announce_event("pfl", _("No next track to mix"))
            return False
        next_item = playlist.items[next_idx]

        overrides = dict(overrides or {})
        preview_pre_seconds = overrides.pop("_preview_pre_seconds", None)
        mix_plans = getattr(self, "_mix_plans", None)
        plan = mix_plans.get((playlist.id, item.id)) if mix_plans else None
        if plan and not overrides and plan.mix_at is not None:
            mix_at = plan.mix_at
            fade_seconds = plan.fade_seconds
            base_cue = plan.base_cue
            effective_duration = plan.effective_duration
        else:
            effective_override = self._measure_effective_duration(playlist, item)
            mix_at, fade_seconds, base_cue, effective_duration = self._resolve_mix_timing(
                item,
                overrides,
                effective_duration_override=effective_override,
            )
        pre_seconds = 4.0 if preview_pre_seconds is None else max(0.0, float(preview_pre_seconds))

        ok = self._playback.start_mix_preview(
            item,
            next_item,
            mix_at_seconds=mix_at,
            pre_seconds=pre_seconds,
            fade_seconds=fade_seconds,
            current_effective_duration=effective_duration,
            next_cue_override=next_item.cue_in_seconds or 0.0,
        )
        logger.debug(
            "UI: PFL mix preview scheduled mix_at=%s fade=%.3f cue=%.3f effective=%.3f seg=%s ovl=%s",
            f"{mix_at:.3f}" if mix_at is not None else "None",
            fade_seconds,
            base_cue,
            effective_duration,
            overrides.get("segue"),
            overrides.get("overlap"),
        )
        if not ok:
            self._announce_event("pfl", _("No next track to mix"))
        return ok


class ManagePlaylistsDialog(wx.Dialog):
    """Allow users to reorder, remove, and configure active playlists."""

    KIND_LABELS = {
        PlaylistKind.MUSIC: _("Music"),
        PlaylistKind.NEWS: _("News"),
        PlaylistKind.FOLDER: _("Music folder"),
    }

    def __init__(
        self,
        parent: wx.Window,
        entries: list[dict[str, Any]],
        *,
        create_callback: Callable[[], PlaylistModel | None] | None = None,
        configure_callback: Callable[[str], list[str | None] | None] | None = None,
    ) -> None:
        super().__init__(parent, title=_("Manage playlists"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._entries: list[dict[str, Any]] = [
            {
                "id": entry["id"],
                "name": entry["name"],
                "kind": entry["kind"],
                "slots": list(entry.get("slots", [])),
            }
            for entry in entries
        ]
        self._removed: list[str] = []
        self._create_callback = create_callback
        self._configure_callback = configure_callback

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(self, label=_("Current playlists (top = first in sequence):"))
        main_sizer.Add(label, 0, wx.ALL, 5)

        self._list_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._list_ctrl.InsertColumn(0, _("Name"))
        self._list_ctrl.InsertColumn(1, _("Type"))
        self._list_ctrl.InsertColumn(2, _("Players"))
        main_sizer.Add(self._list_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        controls_row = wx.BoxSizer(wx.HORIZONTAL)
        self._add_button = wx.Button(self, label=_("Add"))
        self._configure_button = wx.Button(self, label=_("Configure players…"))
        self._remove_button = wx.Button(self, label=_("Remove"))
        controls_row.Add(self._add_button, 0, wx.ALL, 5)
        controls_row.Add(self._configure_button, 0, wx.ALL, 5)
        controls_row.Add(self._remove_button, 0, wx.ALL, 5)
        main_sizer.Add(controls_row, 0, wx.ALIGN_LEFT)

        move_row = wx.BoxSizer(wx.HORIZONTAL)
        self._up_button = wx.Button(self, label=_("Move up"))
        self._down_button = wx.Button(self, label=_("Move down"))
        move_row.Add(self._up_button, 0, wx.ALL, 5)
        move_row.Add(self._down_button, 0, wx.ALL, 5)
        main_sizer.Add(move_row, 0, wx.ALIGN_LEFT)

        action_sizer = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if action_sizer:
            main_sizer.Add(action_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self._add_button.Bind(wx.EVT_BUTTON, self._add_entry)
        self._remove_button.Bind(wx.EVT_BUTTON, self._remove_entry)
        self._configure_button.Bind(wx.EVT_BUTTON, self._configure_entry)
        self._up_button.Bind(wx.EVT_BUTTON, lambda _evt: self._move_entry(-1))
        self._down_button.Bind(wx.EVT_BUTTON, lambda _evt: self._move_entry(1))
        self._list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda _evt: self._update_button_states())
        self._list_ctrl.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda _evt: self._update_button_states())
        self._list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._handle_activate)

        self.SetSizer(main_sizer)
        self.SetSize((520, 420))
        self._refresh_list()

    def _selected_index(self) -> int:
        return self._list_ctrl.GetFirstSelected()

    def _selected_entry(self) -> dict[str, Any] | None:
        index = self._selected_index()
        if index == wx.NOT_FOUND or index >= len(self._entries):
            return None
        return self._entries[index]

    def _refresh_list(self, *, select_id: str | None = None) -> None:
        self._list_ctrl.DeleteAllItems()
        for entry in self._entries:
            index = self._list_ctrl.InsertItem(self._list_ctrl.GetItemCount(), entry["name"])
            kind_label = self.KIND_LABELS.get(entry["kind"], "")
            self._list_ctrl.SetItem(index, 1, kind_label)
            self._list_ctrl.SetItem(index, 2, self._format_slot_summary(entry.get("slots", [])))
            self._list_ctrl.SetItemData(index, index)
        for column in range(3):
            self._list_ctrl.SetColumnWidth(column, wx.LIST_AUTOSIZE_USEHEADER)

        selection_index = 0
        if select_id:
            for idx, entry in enumerate(self._entries):
                if entry["id"] == select_id:
                    selection_index = idx
                    break
        if self._entries:
            self._list_ctrl.Select(selection_index)
        self._update_button_states()

    def _update_button_states(self) -> None:
        selection = self._selected_index()
        can_modify = selection != wx.NOT_FOUND
        entry = self._entries[selection] if can_modify else None
        is_folder = bool(entry and entry.get("kind") == PlaylistKind.FOLDER)
        total = len(self._entries)
        self._remove_button.Enable(can_modify and total > 1)
        self._configure_button.Enable(can_modify and self._configure_callback is not None and not is_folder)
        self._up_button.Enable(can_modify and selection > 0)
        self._down_button.Enable(can_modify and selection != wx.NOT_FOUND and selection < total - 1)

    def _move_entry(self, offset: int) -> None:
        selection = self._selected_index()
        if selection == wx.NOT_FOUND:
            return
        target = selection + offset
        if target < 0 or target >= len(self._entries):
            return
        self._entries[selection], self._entries[target] = self._entries[target], self._entries[selection]
        self._refresh_list(select_id=self._entries[target]["id"])

    def _remove_entry(self, _event: wx.CommandEvent) -> None:
        selection = self._selected_index()
        if selection == wx.NOT_FOUND:
            return
        if len(self._entries) <= 1:
            wx.MessageBox(_("At least one playlist must remain."), _("Warning"), parent=self)
            return
        removed_entry = self._entries.pop(selection)
        self._removed.append(removed_entry["id"])
        next_selection = None
        if self._entries:
            next_index = min(selection, len(self._entries) - 1)
            next_selection = self._entries[next_index]["id"]
        self._refresh_list(select_id=next_selection)

    def _configure_entry(self, _event: wx.CommandEvent) -> None:
        if not self._configure_callback:
            return
        entry = self._selected_entry()
        if not entry:
            return
        slots = self._configure_callback(entry["id"])
        if slots is None:
            return
        entry["slots"] = list(slots)
        self._refresh_list(select_id=entry["id"])

    def _handle_activate(self, _event: wx.ListEvent) -> None:
        self._configure_entry(_event)

    def get_result(self) -> Optional[dict[str, list[str]]]:
        if not self._entries:
            return None
        return {
            "order": [entry["id"] for entry in self._entries],
            "removed": list(self._removed),
        }

    def _add_entry(self, _event: wx.CommandEvent) -> None:
        if not self._create_callback:
            return
        model = self._create_callback()
        if model is None:
            return
        self._entries.append(
            {"id": model.id, "name": model.name, "kind": model.kind, "slots": list(model.get_configured_slots())}
        )
        self._refresh_list(select_id=model.id)

    @staticmethod
    def _format_slot_summary(slots: list[str | None]) -> str:
        return str(sum(1 for slot in slots if slot))
