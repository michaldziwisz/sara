"""Main window of the SARA application."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import as_file, files
import logging
import os
import tempfile
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from typing import Any, Callable, Dict, List, Optional, Tuple

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
from sara.ui.new_playlist_dialog import NewPlaylistDialog
from sara.ui.playlist_panel import PlaylistPanel
from sara.ui.news_playlist_panel import NewsPlaylistPanel
from sara.ui.playlist_devices_dialog import PlaylistDevicesDialog
from sara.ui.mix_point_dialog import MixPointEditorDialog
from sara.ui.options_dialog import OptionsDialog
from sara.ui.shortcut_editor_dialog import ShortcutEditorDialog
from sara.ui.shortcut_utils import format_shortcut_display, parse_shortcut
from sara.ui.nvda_sleep import notify_nvda_play_next
from sara.ui.speech import cancel_speech, speak_text
from sara.ui.file_selection_dialog import FileSelectionDialog


logger = logging.getLogger(__name__)


@dataclass
class PlaybackContext:
    player: Player
    path: Path
    device_id: str
    slot_index: int
    intro_seconds: float | None = None
    intro_alert_triggered: bool = False


@dataclass
class PreviewContext:
    player: Player
    device_id: str
    item_path: Path
    finished_event: Event | None = None


FADE_DURATION_SECONDS = 2.0


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
        self._settings = settings or SettingsManager()
        set_language(self._settings.get_language())
        if not self._settings.config_path.exists():
            self._settings.save()
        self._playlists: Dict[str, PlaylistPanel] = {}
        self._playlist_wrappers: Dict[str, wx.Window] = {}
        self._playlist_headers: Dict[str, wx.StaticText] = {}
        self._playlist_titles: Dict[str, str] = {}
        self._playlist_order: list[str] = []
        self._current_panel_id: str | None = None
        self._playback_contexts: Dict[tuple[str, str], PlaybackContext] = {}
        self._current_index: int = 0
        self._state = state or AppState()
        self._playlist_factory = PlaylistFactory()
        self._audio_engine = AudioEngine()
        self._play_next_id = wx.NewIdRef()
        self._add_tracks_id = wx.NewIdRef()
        self._assign_device_id = wx.NewIdRef()
        self._auto_mix_toggle_id = wx.NewIdRef()
        self._loop_playback_toggle_id = wx.NewIdRef()
        self._loop_info_id = wx.NewIdRef()
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
        self._preview_context: PreviewContext | None = None
        self._auto_mix_enabled: bool = False
        self._auto_mix_state: Dict[tuple[str, str], bool] = {}
        self._alternate_play_next: bool = self._settings.get_alternate_play_next()
        self._auto_remove_played: bool = self._settings.get_auto_remove_played()
        self._focus_playing_track: bool = self._settings.get_focus_playing_track()
        self._intro_alert_seconds: float = self._settings.get_intro_alert_seconds()
        self._pfl_device_id: str | None = self._settings.get_pfl_device()
        self._clipboard_items: List[Dict[str, Any]] = []
        self._undo_stack: list[UndoAction] = []
        self._redo_stack: list[UndoAction] = []
        self._focus_lock: Dict[str, bool] = {}
        self._intro_alert_players: list[Tuple[Player, Path]] = []
        self._last_started_item_id: Dict[str, str | None] = {}

        self._ensure_legacy_hooks()

        self.CreateStatusBar()
        self.SetStatusText(_("Ready"))
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
        if self._playlist_order:
            wx.CallAfter(self._focus_playlist_panel, self._playlist_order[0])

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
            model = self._playlist_factory.create_playlist(name, kind=kind)
            slots = entry.get("slots", [])
            if isinstance(slots, list):
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
        if keycode == wx.WXK_F6:
            if self._cycle_playlist_focus(backwards=event.ShiftDown()):
                return
        panel, focus = self._active_news_panel()
        if keycode == wx.WXK_SPACE and panel and panel.is_edit_control(focus):
            event.Skip()
            event.StopPropagation()
            return
        event.Skip()

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
            )
        else:
            panel = PlaylistPanel(
                container,
                model=model,
                on_focus=self._on_playlist_focus,
                on_mix_configure=self._on_mix_points_configure,
                on_toggle_selection=self._on_toggle_selection,
                on_selection_change=self._on_playlist_selection_change,
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
        if model.id not in self._playlist_order:
            self._playlist_order.append(model.id)
        if self._current_panel_id is None:
            self._current_panel_id = model.id
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
        filtered = [playlist_id for playlist_id in order if playlist_id in self._playlists]
        remaining = [playlist_id for playlist_id in self._playlist_order if playlist_id not in filtered]
        self._playlist_order = filtered + remaining
        self._playlist_sizer.Clear(delete_windows=False)
        for playlist_id in self._playlist_order:
            wrapper = self._playlist_wrappers.get(playlist_id)
            if wrapper is not None:
                self._playlist_sizer.Add(wrapper, 0, wx.EXPAND | wx.ALL, 8)
        self._playlist_container.Layout()
        self._playlist_container.FitInside()
        if self._current_panel_id not in self._playlist_order:
            self._current_panel_id = self._playlist_order[0] if self._playlist_order else None
        if self._current_panel_id and self._current_panel_id in self._playlist_order:
            self._current_index = self._playlist_order.index(self._current_panel_id)
        else:
            self._current_index = 0
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
        self._playlist_order = [pid for pid in self._playlist_order if pid != playlist_id]
        self._playlist_titles.pop(playlist_id, None)
        self._playlist_container.Layout()
        self._playlist_container.FitInside()
        self._auto_mix_state = {key: value for key, value in self._auto_mix_state.items() if key[0] != playlist_id}
        self._playback_contexts = {key: value for key, value in self._playback_contexts.items() if key[0] != playlist_id}
        self._last_started_item_id.pop(playlist_id, None)
        self._apply_playlist_order(self._playlist_order)
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

    def _persist_playlist_outputs(self, model: PlaylistModel) -> None:
        self._settings.set_playlist_outputs(model.name, model.get_configured_slots())
        self._settings.save()
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
        order = [playlist_id for playlist_id in self._playlist_order if playlist_id in self._playlists]
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
        if not self._focus_playing_track:
            return
        playing_id = self._get_playing_item_id(playlist_id)
        panel = self._playlists.get(playlist_id)
        if not isinstance(panel, PlaylistPanel):
            return
        if playing_id is None:
            self._focus_lock[playlist_id] = False
            return
        if not indices:
            self._focus_lock[playlist_id] = False
            return
        if len(indices) == 1:
            selected_index = indices[0]
            if 0 <= selected_index < len(panel.model.items):
                selected_item = panel.model.items[selected_index]
                if selected_item.id == playing_id:
                    self._focus_lock[playlist_id] = False
                    return
        self._focus_lock[playlist_id] = True

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
            )
            self.add_playlist(model)
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
        wildcard = _("Audio files (*.mp3;*.wav;*.flac;*.ogg)|*.mp3;*.wav;*.flac;*.ogg|All files|*.*")
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
        playlist_id = self._current_panel_id
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
        for playlist_id in self._playlist_order:
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
            self._reload_pfl_device()
            self._alternate_play_next = self._settings.get_alternate_play_next()
            self._auto_remove_played = self._settings.get_auto_remove_played()
            self._focus_playing_track = self._settings.get_focus_playing_track()
            self._intro_alert_seconds = self._settings.get_intro_alert_seconds()
            self._refresh_news_panels()
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
        self._auto_mix_enabled = not self._auto_mix_enabled
        if not self._auto_mix_enabled:
            self._auto_mix_state.clear()
        status = _("enabled") if self._auto_mix_enabled else _("disabled")
        self._announce_event("auto_mix", _("Auto mix %s") % status)
        if self._auto_mix_enabled:
            panel = self._get_current_music_panel()
            if panel is not None and self._get_playback_context(panel.model.id) is None:
                if not self._start_next_from_playlist(panel, ignore_ui_selection=False, advance_focus=False):
                    self._announce_event("playback_events", _("No scheduled tracks available"))

    def _on_toggle_loop_playback(self, _event: wx.CommandEvent) -> None:
        context = self._get_selected_context()
        if context is None:
            return
        panel, model, indices = context
        index = indices[0]
        if not (0 <= index < len(model.items)):
            self._announce_event("playlist", _("No track selected"))
            return

        item = model.items[index]
        if not item.has_loop():
            self._announce_event("loop", _("Track has no loop defined"))
            return

        item.loop_enabled = not item.loop_enabled

        if not save_loop_metadata(item.path, item.loop_start_seconds, item.loop_end_seconds, item.loop_enabled):
            self._announce_event("loop", _("Failed to update loop metadata"))

        self._apply_loop_setting_to_playback(playlist_id=model.id, item_id=item.id)

        state = _("enabled") if item.loop_enabled else _("disabled")
        self._announce_event("loop", _("Track looping %s") % state)
        if not item.loop_enabled:
            remaining = self._compute_intro_remaining(item)
            if remaining is not None:
                self._announce_intro_remaining(remaining)
        panel.refresh()

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

    def _apply_loop_setting_to_playback(self, *, playlist_id: str | None = None, item_id: str | None = None) -> None:
        for (pl_id, item_id_key), context in list(self._playback_contexts.items()):
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
            self._announce_event("selection", _("Track %s selected in playlist %s") % (item.title, playlist.name))
        else:
            self._announce_event("selection", _("Selection removed from %s") % item.title)

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
            overlap_seconds=item.overlap_seconds,
            on_preview=lambda position, loop_range=None: self._start_pfl_preview(
                item,
                max(0.0, position),
                loop_range=loop_range,
            ),
            on_stop_preview=self._stop_pfl_preview,
            track_path=item.path,
            initial_replay_gain=item.replay_gain_db,
            on_replay_gain_update=lambda gain, item=item: self._apply_replay_gain(item, gain),
            loop_start_seconds=item.loop_start_seconds,
            loop_end_seconds=item.loop_end_seconds,
            loop_enabled=item.loop_enabled,
        )

        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            result = dialog.get_result()
        finally:
            dialog.Destroy()
            self._stop_pfl_preview()

        mix_values = {
            "cue_in": result.get("cue"),
            "intro": result.get("intro"),
            "outro": result.get("outro"),
            "segue": result.get("segue"),
            "overlap": result.get("overlap"),
        }

        item.cue_in_seconds = mix_values["cue_in"]
        item.intro_seconds = mix_values["intro"]
        item.outro_seconds = mix_values["outro"]
        item.segue_seconds = mix_values["segue"]
        item.overlap_seconds = mix_values["overlap"]

        if not save_mix_metadata(
            item.path,
            cue_in=item.cue_in_seconds,
            intro=item.intro_seconds,
            outro=item.outro_seconds,
            segue=item.segue_seconds,
            overlap=item.overlap_seconds,
        ):
            self._announce_event("pfl", _("Failed to update mix metadata"))
        else:
            self._announce_event("pfl", _("Updated mix points for %s") % item.title)

        panel.refresh()

        loop_info = result.get("loop") or {}
        loop_defined = bool(loop_info.get("enabled"))
        loop_start = loop_info.get("start")
        loop_end = loop_info.get("end")
        if loop_defined and loop_start is not None and loop_end is not None and loop_end > loop_start:
            try:
                item.set_loop(loop_start, loop_end)
            except ValueError as exc:
                self._announce_event("loop", str(exc))
            else:
                if not save_loop_metadata(item.path, loop_start, loop_end, item.loop_enabled):
                    self._announce_event("loop", _("Failed to update loop metadata"))
                self._apply_loop_setting_to_playback(playlist_id=playlist_id, item_id=item.id)
                panel.refresh()
        else:
            if item.has_loop() or item.loop_enabled:
                item.clear_loop()
                save_loop_metadata(item.path, None, None)
                self._apply_loop_setting_to_playback(playlist_id=playlist_id, item_id=item.id)
                panel.refresh()

    def _start_playback(self, panel: PlaylistPanel, item: PlaylistItem) -> bool:
        playlist = panel.model
        key = (playlist.id, item.id)

        # stop any preview playback before starting actual playback
        self._stop_pfl_preview()

        if not item.path.exists():
            item.status = PlaylistItemStatus.PENDING
            panel.mark_item_status(item.id, item.status)
            panel.refresh()
            self._announce_event("playback_errors", _("File %s does not exist") % item.path)
            return False

        context = self._playback_contexts.get(key)
        device_id = context.device_id if context else None
        slot_index = context.slot_index if context else None
        player = context.player if context else None

        if player is None or device_id is None or slot_index is None:
            existing_context = self._get_playback_context(playlist.id)
            if existing_context:
                existing_key, _existing = existing_context
                auto_active = self._auto_mix_enabled and self._auto_mix_state.get(existing_key)
                if not auto_active:
                    fade_seconds = self._fade_duration
                    self._stop_playlist_playback(playlist.id, mark_played=True, fade_duration=fade_seconds)

            acquired = self._ensure_player(playlist)
            if acquired is None:
                item.status = PlaylistItemStatus.PENDING
                panel.mark_item_status(item.id, item.status)
                panel.refresh()
                self._announce_event("device", _("No audio devices available"))
                return False
            player, device_id, slot_index = acquired

        def _on_finished(finished_item_id: str) -> None:
            wx.CallAfter(self._handle_playback_finished, playlist.id, finished_item_id)

        def _on_progress(progress_item_id: str, seconds: float) -> None:
            wx.CallAfter(self._handle_playback_progress, playlist.id, progress_item_id, seconds)

        player.set_finished_callback(_on_finished)
        player.set_progress_callback(_on_progress)

        start_seconds = item.cue_in_seconds or 0.0

        notify_nvda_play_next()

        try:
            player.play(item.id, str(item.path), start_seconds=start_seconds)
        except Exception as exc:  # pylint: disable=broad-except
            player.set_finished_callback(None)
            player.set_progress_callback(None)
            item.status = PlaylistItemStatus.PENDING
            panel.mark_item_status(item.id, item.status)
            panel.refresh()
            self._announce_event("playback_errors", _("Playback error: %s") % exc)
            return False

        try:
            player.set_gain_db(item.replay_gain_db)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to set ReplayGain: %s", exc)

        try:
            if item.loop_enabled and item.has_loop():
                player.set_loop(item.loop_start_seconds, item.loop_end_seconds)
            else:
                player.set_loop(None, None)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to configure loop: %s", exc)

        self._playback_contexts[key] = PlaybackContext(
            player=player,
            path=item.path,
            device_id=device_id,
            slot_index=slot_index,
            intro_seconds=item.intro_seconds,
        )
        self._auto_mix_state.pop(key, None)
        panel.mark_item_status(item.id, item.status)
        panel.refresh()
        self._focus_lock[playlist.id] = False
        self._maybe_focus_playing_item(panel, item.id)
        if item.has_loop() and item.loop_enabled:
            self._announce_event("loop", _("Loop playing"))
        return True

    def _start_next_from_playlist(
        self,
        panel: PlaylistPanel,
        *,
        ignore_ui_selection: bool = False,
        advance_focus: bool = True,
    ) -> bool:
        playlist = panel.model
        if not playlist.items:
            self._announce_event("playlist", _("Playlist %s is empty") % playlist.name)
            return False

        consumed_model_selection = False
        preferred_item_id = playlist.next_selected_item_id()
        play_index: int | None = None

        used_ui_selection = False

        if preferred_item_id:
            consumed_model_selection = True
            play_index = self._index_of_item(playlist, preferred_item_id)
        else:
            if not ignore_ui_selection:
                selected_indices = panel.get_selected_indices()
            else:
                selected_indices = []
            if selected_indices:
                play_index = selected_indices[0]
                used_ui_selection = True
            elif not ignore_ui_selection:
                focus_index = panel.get_focused_index()
                if focus_index != wx.NOT_FOUND:
                    play_index = focus_index
                    used_ui_selection = True
                else:
                    play_index = self._derive_next_play_index(playlist)
            else:
                play_index = self._derive_next_play_index(playlist)
            if play_index is not None and 0 <= play_index < len(playlist.items):
                preferred_item_id = playlist.items[play_index].id
            else:
                preferred_item_id = None

        item = playlist.begin_next_item(preferred_item_id)
        if not item:
            self._announce_event("playback_events", _("No scheduled tracks in playlist %s") % playlist.name)
            return False

        if self._start_playback(panel, item):
            self._last_started_item_id[playlist.id] = item.id
            track_name = self._format_track_name(item)
            if consumed_model_selection and item.id == preferred_item_id:
                playlist.clear_selection(item.id)
                self._refresh_selection_display(playlist.id)
            if advance_focus and not consumed_model_selection and not used_ui_selection:
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
        ordered_ids = [playlist_id for playlist_id in self._playlist_order if playlist_id in self._playlists]
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
                self._current_panel_id = playlist_id
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

        if not self._start_next_from_playlist(panel):
            self._announce_event("playback_events", _("No scheduled tracks available"))

    def _handle_playback_finished(self, playlist_id: str, item_id: str) -> None:
        self._auto_mix_state.pop((playlist_id, item_id), None)
        context = self._playback_contexts.pop((playlist_id, item_id), None)
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
        if self._auto_remove_played:
            removed_item = self._remove_item_from_playlist(panel, model, item_index, refocus=True)
            self._announce_event("playback_events", _("Removed played track %s") % removed_item.title)
            removed = True
        else:
            model.mark_played(item_id)
            panel.mark_item_status(item_id, item.status)
            panel.refresh()

        if context:
            try:
                context.player.stop()
            except Exception as exc:  # pylint: disable=broad-except
                self._announce_event("playback_errors", _("Player stop error: %s") % exc)
        if not removed:
            self._announce_event("playback_events", _("Finished %s") % item.title)

    def _handle_playback_progress(self, playlist_id: str, item_id: str, seconds: float) -> None:
        context_entry = self._playback_contexts.get((playlist_id, item_id))
        if not context_entry:
            return
        panel = self._playlists.get(playlist_id)
        if not panel:
            return
        item = next((track for track in panel.model.items if track.id == item_id), None)
        if not item:
            return
        item.update_progress(seconds)
        panel.update_progress(item_id)
        self._maybe_focus_playing_item(panel, item_id)
        self._consider_intro_alert(panel, item, context_entry, seconds)

        queued_selection = self._playlist_has_selection(playlist_id)
        mix_enabled = self._auto_mix_enabled or queued_selection

        if mix_enabled:
            key = (playlist_id, item_id)
            if not self._auto_mix_state.get(key):
                target = item.segue_seconds
                overlap = item.overlap_seconds
                if target is None and item.outro_seconds is not None:
                    cue_offset = item.cue_in_seconds or 0.0
                    relative_outro = item.outro_seconds - cue_offset
                    if relative_outro >= 0.0:
                        target = relative_outro
                default_overlap = overlap if overlap and overlap > 0 else self._fade_duration
                if target is None and item.effective_duration_seconds > 0 and default_overlap:
                    target = max(0.0, item.effective_duration_seconds - default_overlap)
                if target is not None:
                    progress = seconds - (item.cue_in_seconds or 0.0)
                    if progress >= target:
                        self._auto_mix_state[key] = True
                        next_started = self._start_next_from_playlist(
                            panel,
                            ignore_ui_selection=self._auto_mix_enabled,
                            advance_focus=False,
                        )
                        if not next_started:
                            self._auto_mix_state[key] = False
                            return
                        try:
                            if default_overlap and default_overlap > 0:
                                context_entry.player.fade_out(default_overlap)
                            else:
                                context_entry.player.stop()
                        except Exception as exc:  # pylint: disable=broad-except
                            logger.warning("Auto mix fade out failed: %s", exc)

    def _on_playlist_hotkey(self, event: wx.CommandEvent) -> None:
        action = self._action_by_id.get(event.GetId())
        if not action:
            return

        panel = self._get_current_music_panel()
        if panel is None:
            self._announce_event("playlist", _("Select a playlist first"))
            return

        playlist = panel.model
        if action == "play":
            self._start_next_from_playlist(panel)
            return

        context_entry = self._get_playback_context(playlist.id)
        if context_entry is None:
            self._announce_event("playback_events", _("No active playback for this playlist"))
            return

        key, context = context_entry
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
            self._playback_contexts[key] = context
            self._announce_event("playback_events", f"Playlista {playlist.name} wstrzymana")
        elif action == "stop":
            self._stop_playlist_playback(playlist.id, mark_played=False, fade_duration=0.0)
            self._announce_event("playback_events", f"Playlista {playlist.name} zatrzymana")
        elif action == "fade":
            self._stop_playlist_playback(playlist.id, mark_played=True, fade_duration=self._fade_duration)
            if item:
                panel.mark_item_status(item.id, item.status)
                panel.refresh()
            self._announce_event(
                "playback_events",
                _("Playlist %s finished track with fade out") % playlist.name,
            )
    def _get_current_playlist_panel(self):
        if self._current_panel_id and self._current_panel_id in self._playlists:
            return self._playlists[self._current_panel_id]

        for playlist_id in self._playlist_order:
            panel = self._playlists.get(playlist_id)
            if panel:
                self._current_panel_id = playlist_id
                try:
                    self._current_index = self._playlist_order.index(playlist_id)
                except ValueError:
                    pass
                self._update_active_playlist_styles()
                self._announce_event("playlist", panel.model.name)
                return panel
        return None

    def _get_current_music_panel(self) -> PlaylistPanel | None:
        panel = self._get_current_playlist_panel()
        if isinstance(panel, PlaylistPanel):
            return panel
        return None

    def _handle_focus_click(self, event: wx.MouseEvent, playlist_id: str) -> None:
        self._focus_playlist_panel(playlist_id)
        event.Skip()

    def _on_playlist_focus(self, playlist_id: str) -> None:
        if playlist_id not in self._playlists:
            return
        previous_id = self._current_panel_id
        if previous_id == playlist_id:
            return
        self._current_panel_id = playlist_id
        try:
            self._current_index = self._playlist_order.index(playlist_id)
        except ValueError:
            pass
        self._update_active_playlist_styles()
        panel = self._playlists.get(playlist_id)
        if panel:
            self._announce_event("playlist", panel.model.name)

    def _get_selected_context(self) -> tuple[PlaylistPanel, PlaylistModel, list[int]] | None:
        panel = self._get_current_music_panel()
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

    def _get_selected_items(self) -> tuple[PlaylistPanel, PlaylistModel, list[tuple[int, PlaylistItem]]] | None:
        context = self._get_selected_context()
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
                    "overlap": item.overlap_seconds,
                    "intro": item.intro_seconds,
                    "outro": item.outro_seconds,
                    "loop_start": item.loop_start_seconds,
                    "loop_end": item.loop_end_seconds,
                    "loop_enabled": item.loop_enabled,
                }
            )
        return serialized

    def _create_item_from_serialized(self, data: Dict[str, Any]) -> PlaylistItem:
        path = Path(data["path"])
        item = self._playlist_factory.create_item(
            path=path,
            title=data.get("title", path.stem),
            artist=data.get("artist"),
            duration_seconds=float(data.get("duration", 0.0)),
            replay_gain_db=data.get("replay_gain_db"),
            cue_in_seconds=data.get("cue_in"),
            segue_seconds=data.get("segue"),
            overlap_seconds=data.get("overlap"),
            intro_seconds=data.get("intro"),
            outro_seconds=data.get("outro"),
            loop_start_seconds=data.get("loop_start"),
            loop_end_seconds=data.get("loop_end"),
            loop_enabled=bool(data.get("loop_enabled")),
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
            overlap_seconds=metadata.overlap_seconds,
            intro_seconds=metadata.intro_seconds,
            outro_seconds=metadata.outro_seconds,
            loop_start_seconds=metadata.loop_start_seconds,
            loop_end_seconds=metadata.loop_end_seconds,
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
        if not self._focus_playing_track or self._auto_mix_enabled:
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

    def _announce_intro_remaining(self, remaining: float) -> None:
        message = _("Intro remaining: {seconds:.0f} seconds").format(seconds=max(0.0, remaining))
        self._announce_event("intro_alert", message)

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
        pfl_device_id = self._pfl_device_id or self._settings.get_pfl_device()
        if not pfl_device_id:
            return False
        if self._preview_context:
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
            player.play("intro-alert", str(tmp_path))
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

    def _remove_item_from_playlist(
        self, panel: PlaylistPanel, model: PlaylistModel, index: int, *, refocus: bool = True
    ) -> PlaylistItem:
        item = model.items.pop(index)
        was_selected = item.is_selected
        item.is_selected = was_selected
        self._forget_last_started_item(model.id, item.id)
        if any(key == (model.id, item.id) for key in self._playback_contexts):
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
        self._undo_stack.append(UndoAction(model.id, operation))
        self._redo_stack.clear()

    def _apply_undo_action(self, action: UndoAction, *, reverse: bool) -> bool:
        model = self._get_playlist_model(action.playlist_id)
        panel = self._playlists.get(action.playlist_id)
        if model is None or panel is None:
            return False
        if self._current_panel_id != action.playlist_id:
            self._current_panel_id = action.playlist_id
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
        context = self._get_selected_items()
        if context is None:
            return
        panel, model, selected = context
        items = [item for _, item in selected]
        self._clipboard_items = self._serialize_items(items)
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
        self._clipboard_items = self._serialize_items(items)
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

        if self._clipboard_items:
            new_items = [self._create_item_from_serialized(data) for data in self._clipboard_items]
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
        if not self._undo_stack:
            self._announce_event("undo_redo", _("Nothing to undo"))
            return
        action = self._undo_stack.pop()
        if not self._apply_undo_action(action, reverse=True):
            self._announce_event("undo_redo", _("Unable to undo last operation"))
            return
        self._redo_stack.append(action)
        self._announce_operation(action.operation, undo=True)

    def _on_redo(self, _event: wx.CommandEvent) -> None:
        if not self._redo_stack:
            self._announce_event("undo_redo", _("Nothing to redo"))
            return
        action = self._redo_stack.pop()
        if not self._apply_undo_action(action, reverse=False):
            self._announce_event("undo_redo", _("Unable to redo last operation"))
            return
        self._undo_stack.append(action)
        self._announce_operation(action.operation, undo=False)

    def _update_active_playlist_styles(self) -> None:
        active_colour = wx.Colour(230, 240, 255)
        inactive_colour = self._playlist_container.GetBackgroundColour()
        active_text_colour = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
        inactive_text_colour = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)

        for playlist_id, wrapper in self._playlist_wrappers.items():
            is_active = playlist_id == self._current_panel_id
            wrapper.SetBackgroundColour(active_colour if is_active else inactive_colour)
            wrapper.Refresh()
            panel = self._playlists.get(playlist_id)
            if panel:
                panel.set_active(is_active)

        for playlist_id, header in self._playlist_headers.items():
            is_active = playlist_id == self._current_panel_id
            base_title = self._playlist_titles.get(playlist_id, header.GetLabel())
            if header.GetLabel() != base_title:
                header.SetLabel(base_title)
            header.SetForegroundColour(active_text_colour if is_active else inactive_text_colour)
            header.Refresh()

        self._playlist_container.Refresh()

    def _get_playback_context(self, playlist_id: str) -> tuple[tuple[str, str], PlaybackContext] | None:
        for key, context in self._playback_contexts.items():
            if key[0] == playlist_id:
                return key, context
        return None

    def _get_playing_item_id(self, playlist_id: str) -> str | None:
        context = self._get_playback_context(playlist_id)
        if context is None:
            return None
        key, _ctx = context
        return key[1]

    def _get_busy_device_ids(self) -> set[str]:
        return {context.device_id for context in self._playback_contexts.values()}

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
        keys_to_remove = [key for key in self._playback_contexts if key[0] == playlist_id]
        for key in keys_to_remove:
            self._auto_mix_state.pop(key, None)
            context = self._playback_contexts.pop(key)
            try:
                if fade_duration > 0.0:
                    context.player.fade_out(fade_duration)
                else:
                    context.player.stop()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Failed to stop player: %s", exc)
            try:
                context.player.set_finished_callback(None)
                context.player.set_progress_callback(None)
            except Exception:  # pylint: disable=broad-except
                pass

            panel = self._playlists.get(playlist_id)
            if not panel:
                continue
            item = next((track for track in panel.model.items if track.id == key[1]), None)
            if not item:
                continue

            if mark_played:
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

    def _stop_pfl_preview(self, *, wait: bool = True) -> None:
        if not self._preview_context:
            return
        context = self._preview_context
        self._preview_context = None
        finished_event = context.finished_event if wait else None
        try:
            context.player.set_loop(None, None)
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            context.player.stop()
        except Exception:  # pylint: disable=broad-except
            pass
        if wait and finished_event:
            try:
                finished_event.wait(timeout=0.5)
            except Exception:  # pylint: disable=broad-except
                pass

    def _reload_pfl_device(self) -> None:
        new_device = self._settings.get_pfl_device()
        if new_device != self._pfl_device_id:
            self._stop_pfl_preview()
        self._pfl_device_id = new_device

    def _start_pfl_preview(
        self,
        item: PlaylistItem,
        start: float,
        *,
        loop_range: tuple[float, float] | None = None,
    ) -> bool:
        if loop_range is not None and loop_range[1] <= loop_range[0]:
            self._announce_event("loop", _("Loop end must be greater than start"))
            return False

        self._stop_pfl_preview(wait=True)

        pfl_device_id = self._pfl_device_id or self._settings.get_pfl_device()
        if not pfl_device_id:
            self._announce_event("pfl", _("Configure a PFL device in Options"))
            return False

        known_devices = {device.id for device in self._audio_engine.get_devices()}
        if pfl_device_id not in known_devices:
            self._audio_engine.refresh_devices()
            known_devices = {device.id for device in self._audio_engine.get_devices()}
        if pfl_device_id not in known_devices:
            self._announce_event("pfl", _("Selected PFL device is not available"))
            return False

        busy_devices = self._get_busy_device_ids()
        if pfl_device_id in busy_devices:
            self._announce_event("pfl", _("PFL device is currently in use"))
            return False

        player: Player
        try:
            player = self._audio_engine.create_player(pfl_device_id)
        except Exception as exc:  # pylint: disable=broad-except
            self._announce_event("pfl", _("Failed to prepare PFL preview: %s") % exc)
            return False

        finished_event: Event | None = None
        try:
            player.set_finished_callback(None)
            player.set_progress_callback(None)
            player.set_gain_db(item.replay_gain_db)
            finished_event = player.play(item.id + ":preview", str(item.path), start_seconds=start)
            if loop_range:
                player.set_loop(loop_range[0], loop_range[1])
            else:
                player.set_loop(None, None)
        except Exception as exc:  # pylint: disable=broad-except
            self._announce_event("pfl", _("Preview error: %s") % exc)
            try:
                player.stop()
            except Exception:  # pylint: disable=broad-except
                pass
            return False

        self._preview_context = PreviewContext(
            player=player,
            device_id=pfl_device_id,
            item_path=item.path,
            finished_event=finished_event,
        )
        return True

    def _update_loop_preview(self, item: PlaylistItem, start: float, end: float) -> bool:
        if end <= start:
            return False
        context = self._preview_context
        if not context or context.item_path != item.path:
            return False
        try:
            context.player.set_loop(start, end)
        except Exception as exc:  # pylint: disable=broad-except
            self._announce_event("pfl", _("Preview error: %s") % exc)
            return False
        return True

    def _ensure_player(self, playlist: PlaylistModel) -> tuple[Player, str, int] | None:
        attempts = 0
        missing_devices: set[str] = set()

        while attempts < 2:
            devices = self._audio_engine.get_devices()
            if not devices:
                self._audio_engine.refresh_devices()
                devices = self._audio_engine.get_devices()
                if not devices:
                    return None

            device_map = {device.id: device for device in devices}
            busy_devices = self._get_busy_device_ids()
            selection = playlist.select_next_slot(set(device_map.keys()), busy_devices)
            if selection is None:
                if playlist.get_configured_slots():
                    self._announce_event(
                        "device",
                        _("No configured player for playlist %s is available") % playlist.name,
                    )
                return None

            slot_index, device_id = selection
            device = device_map.get(device_id)
            if device is None:
                missing_devices.add(device_id)
                if playlist.output_slots and 0 <= slot_index < len(playlist.output_slots):
                    playlist.output_slots[slot_index] = None
                    self._settings.set_playlist_outputs(playlist.name, playlist.output_slots)
                    self._settings.save()
                attempts += 1
                self._audio_engine.refresh_devices()
                continue

            try:
                player = self._audio_engine.create_player(device_id)
                return player, device_id, slot_index
            except ValueError:
                attempts += 1
                self._audio_engine.refresh_devices()

        if missing_devices:
            removed_list = ", ".join(sorted(missing_devices))
            self._announce_event(
                "device",
                _("Unavailable devices for playlist %s: %s") % (playlist.name, removed_list),
            )
        return None

    def _announce_event(
        self,
        category: str,
        message: str,
        *,
        spoken_message: str | None = None,
    ) -> None:
        """Announce `message` and optionally override spoken content."""
        self.SetStatusText(message)
        if not self._settings.get_announcement_enabled(category):
            return
        if spoken_message == "":
            self._silence_screen_reader()
            return
        speak_text(spoken_message if spoken_message is not None else message)

    def _silence_screen_reader(self) -> None:
        cancel_speech()

    def _announce(self, message: str) -> None:
        self._announce_event("general", message)


class ManagePlaylistsDialog(wx.Dialog):
    """Allow users to reorder, remove, and configure active playlists."""

    KIND_LABELS = {
        PlaylistKind.MUSIC: _("Music"),
        PlaylistKind.NEWS: _("News"),
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
        total = len(self._entries)
        self._remove_button.Enable(can_modify and total > 1)
        self._configure_button.Enable(can_modify and self._configure_callback is not None)
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
