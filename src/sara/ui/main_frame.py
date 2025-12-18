"""Main window of the SARA application."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import wx

from sara.audio.engine import AudioEngine, Player
from sara.core.app_state import AppState, PlaylistFactory
from sara.core.config import SettingsManager
from sara.core.i18n import gettext as _, set_language
from sara.core.hotkeys import HotkeyAction
from sara.core.media_metadata import (
    save_replay_gain_metadata,
)
from sara.core.mix_planner import (
    MIX_EXPLICIT_PROGRESS_GUARD,
    MIX_NATIVE_EARLY_GUARD,
    MIX_NATIVE_LATE_GUARD,
    MixPlan,
    clear_mix_plan as _clear_mix_plan_impl,
    compute_mix_trigger_seconds as _compute_mix_trigger_seconds_impl,
    mark_mix_triggered as _mark_mix_triggered_impl,
    register_mix_plan as _register_mix_plan_impl,
    resolve_mix_timing as _resolve_mix_timing_impl,
)
from sara.core.playlist import PlaylistItem, PlaylistKind, PlaylistModel
from sara.core.shortcuts import get_shortcut
from sara.ui.undo import InsertOperation, MoveOperation, RemoveOperation, UndoAction
from sara.ui.undo_manager import UndoManager
from sara.ui.playlist_panel import PlaylistPanel
from sara.ui.playlist_layout import PlaylistLayoutManager, PlaylistLayoutState
from sara.ui.announcement_service import AnnouncementService
from sara.ui.shortcut_utils import format_shortcut_display, parse_shortcut
from sara.ui.playback_controller import PlaybackContext, PlaybackController
from sara.ui.auto_mix_tracker import AutoMixTracker
from sara.ui.clipboard_service import PlaylistClipboard
from sara.ui.jingle_controller import JingleController
from sara.ui.controllers.playback_flow import (
    handle_playback_finished as _handle_playback_finished_impl,
    start_next_from_playlist as _start_next_from_playlist_impl,
    start_playback as _start_playback_impl,
)
from sara.ui.controllers.mix_points_controller import (
    on_mix_points_configure as _on_mix_points_configure_impl,
    propagate_mix_points_for_path as _propagate_mix_points_for_path_impl,
)
from sara.ui.controllers.playlist_hotkeys import handle_playlist_hotkey as _handle_playlist_hotkey_impl
from sara.ui.controllers.alerts import (
    announce_intro_remaining as _announce_intro_remaining_impl,
    announce_track_end_remaining as _announce_track_end_remaining_impl,
    cleanup_intro_alert_player as _cleanup_intro_alert_player_impl,
    cleanup_track_end_alert_player as _cleanup_track_end_alert_player_impl,
    compute_intro_remaining as _compute_intro_remaining_impl,
    consider_intro_alert as _consider_intro_alert_impl,
    consider_track_end_alert as _consider_track_end_alert_impl,
    play_intro_alert as _play_intro_alert_impl,
    play_track_end_alert as _play_track_end_alert_impl,
)
from sara.ui.controllers.automix_flow import (
    auto_mix_play_next as _auto_mix_play_next_impl,
    auto_mix_start_index as _auto_mix_start_index_impl,
)
from sara.ui.controllers.playlist_io import (
    on_export_playlist as _on_export_playlist_impl,
    on_import_playlist as _on_import_playlist_impl,
    parse_m3u as _parse_m3u_impl,
)
from sara.ui.controllers.playlists_ui import (
    add_playlist as _add_playlist_impl,
    apply_playlist_order as _apply_playlist_order_impl,
    create_ui as _create_ui_impl,
    populate_startup_playlists as _populate_startup_playlists_impl,
    remove_playlist_by_id as _remove_playlist_by_id_impl,
)
from sara.ui.controllers.playlists_management import (
    configure_playlist_devices as _configure_playlist_devices_impl,
    finalize_add_tracks as _finalize_add_tracks_impl,
    on_add_tracks as _on_add_tracks_impl,
    on_assign_device as _on_assign_device_impl,
    on_manage_playlists as _on_manage_playlists_impl,
    on_remove_playlist as _on_remove_playlist_impl,
    prompt_new_playlist as _prompt_new_playlist_impl,
)
from sara.ui.controllers.edit_actions import (
    apply_undo_callback as _apply_undo_callback_impl,
    finalize_clipboard_paste as _finalize_clipboard_paste_impl,
    move_selection as _move_selection_impl,
    on_copy_selection as _on_copy_selection_impl,
    on_cut_selection as _on_cut_selection_impl,
    on_delete_selection as _on_delete_selection_impl,
    on_paste_selection as _on_paste_selection_impl,
    on_redo as _on_redo_impl,
    on_undo as _on_undo_impl,
    push_undo_action as _push_undo_action_impl,
)
from sara.ui.controllers.folder_playlists import (
    finalize_folder_load as _finalize_folder_load_impl,
    handle_folder_preview as _handle_folder_preview_impl,
    load_folder_items as _load_folder_items_impl,
    load_folder_playlist as _load_folder_playlist_impl,
    reload_folder_playlist as _reload_folder_playlist_impl,
    select_folder_for_playlist as _select_folder_for_playlist_impl,
    send_folder_items_to_music as _send_folder_items_to_music_impl,
    stop_preview as _stop_preview_impl,
    target_music_playlist as _target_music_playlist_impl,
)
from sara.ui.controllers.item_loading import (
    build_playlist_item as _build_playlist_item_impl,
    collect_files_from_paths as _collect_files_from_paths_impl,
    create_items_from_m3u_entries as _create_items_from_m3u_entries_impl,
    create_items_from_paths as _create_items_from_paths_impl,
    load_items_from_sources as _load_items_from_sources_impl,
    load_playlist_item as _load_playlist_item_impl,
    metadata_worker_count as _metadata_worker_count_impl,
    run_item_loader as _run_item_loader_impl,
)
from sara.ui.controllers.playlist_focus import (
    active_news_panel as _active_news_panel_impl,
    cycle_playlist_focus as _cycle_playlist_focus_impl,
    focus_playlist_panel as _focus_playlist_panel_impl,
    focused_playlist_id as _focused_playlist_id_impl,
    get_current_playlist_panel as _get_current_playlist_panel_impl,
    handle_focus_click as _handle_focus_click_impl,
    maybe_focus_playing_item as _maybe_focus_playing_item_impl,
    on_playlist_focus as _on_playlist_focus_impl,
    on_playlist_selection_change as _on_playlist_selection_change_impl,
    refresh_news_panels as _refresh_news_panels_impl,
    update_active_playlist_styles as _update_active_playlist_styles_impl,
)
from sara.ui.controllers.playback_state import (
    cancel_active_playback as _cancel_active_playback_impl,
    get_busy_device_ids as _get_busy_device_ids_impl,
    get_playback_context as _get_playback_context_impl,
    get_playing_item_id as _get_playing_item_id_impl,
    stop_playlist_playback as _stop_playlist_playback_impl,
    supports_mix_trigger as _supports_mix_trigger_impl,
)
from sara.ui.controllers.tools_dialogs import (
    on_edit_shortcuts as _on_edit_shortcuts_impl,
    on_jingles as _on_jingles_impl,
    on_options as _on_options_impl,
)
from sara.ui.controllers.loop_and_remaining import (
    active_playlist_item as _active_playlist_item_impl,
    apply_loop_setting_to_playback as _apply_loop_setting_to_playback_impl,
    on_loop_info as _on_loop_info_impl,
    on_toggle_loop_playback as _on_toggle_loop_playback_impl,
    on_track_remaining as _on_track_remaining_impl,
    resolve_remaining_playback as _resolve_remaining_playback_impl,
    sync_loop_mix_trigger as _sync_loop_mix_trigger_impl,
)
from sara.ui.controllers.menu_and_shortcuts import (
    configure_accelerators as _configure_accelerators_impl,
    create_menu_bar as _create_menu_bar_impl,
    handle_jingles_key as _handle_jingles_key_impl,
)
from sara.ui.mix_preview import (
    measure_effective_duration as _measure_effective_duration_impl,
    preview_mix_with_next as _preview_mix_with_next_impl,
)
from sara.ui.mix_runtime import (
    apply_mix_trigger_to_playback as _apply_mix_trigger_to_playback_impl,
    auto_mix_now as _auto_mix_now_impl,
    auto_mix_state_process as _auto_mix_state_process_impl,
)


logger = logging.getLogger(__name__)


ANNOUNCEMENT_PREFIX = "\uf8ff"


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
        self._jingles_path = self._settings.config_path.parent / "jingles.sarajingles"
        self._jingles = JingleController(
            self._audio_engine,
            self._settings,
            self._announce_event,
            set_path=self._jingles_path,
        )
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
        self._jingles_manage_id = wx.NewIdRef()
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
        self.Bind(wx.EVT_CLOSE, self._on_close)

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
        return _auto_mix_start_index_impl(
            self,
            panel,
            idx,
            restart_playing=restart_playing,
            overlap_trigger=overlap_trigger,
        )

    def _create_menu_bar(self) -> None:
        _create_menu_bar_impl(self)

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
        _create_ui_impl(self)

    def _register_accessibility(self) -> None:
        # Placeholder: konfiguracje wx.Accessible zostaną dodane w przyszłych iteracjach
        pass

    def _populate_startup_playlists(self) -> list[PlaylistModel]:
        return _populate_startup_playlists_impl(self)

    def _configure_accelerators(self) -> None:
        _configure_accelerators_impl(self)

    def _handle_global_char_hook(self, event: wx.KeyEvent) -> None:
        keycode = event.GetKeyCode()
        if self._should_handle_altgr_track_remaining(event, keycode):
            self._on_track_remaining()
            return
        if keycode == wx.WXK_F6:
            if self._cycle_playlist_focus(backwards=event.ShiftDown()):
                return
        if self._handle_jingles_key(event):
            return
        panel, focus = self._active_news_panel()
        if keycode == wx.WXK_SPACE and panel and panel.is_edit_control(focus):
            event.Skip()
            event.StopPropagation()
            return
        event.Skip()

    def _handle_jingles_key(self, event: wx.KeyEvent) -> bool:
        return _handle_jingles_key_impl(self, event)

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
        _add_playlist_impl(self, model)

    def _get_playlist_model(self, playlist_id: str) -> PlaylistModel | None:
        return self._state.playlists.get(playlist_id)

    def _playlist_has_selection(self, playlist_id: str) -> bool:
        model = self._get_playlist_model(playlist_id)
        if not model:
            return False
        return any(item.is_selected for item in model.items)

    def _apply_playlist_order(self, order: list[str]) -> None:
        _apply_playlist_order_impl(self, order)

    def _remove_playlist_by_id(self, playlist_id: str, *, announce: bool = True) -> bool:
        return _remove_playlist_by_id_impl(self, playlist_id, announce=announce)
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
        _select_folder_for_playlist_impl(self, playlist_id)

    def _reload_folder_playlist(self, playlist_id: str) -> None:
        _reload_folder_playlist_impl(self, playlist_id)

    def _load_folder_playlist(self, playlist: PlaylistModel, *, announce: bool = True) -> None:
        _load_folder_playlist_impl(self, playlist, announce=announce)

    def _load_folder_items(self, folder_path: Path) -> tuple[list[PlaylistItem], int]:
        return _load_folder_items_impl(self, folder_path)

    def _finalize_folder_load(
        self,
        playlist_id: str,
        folder_path: Path,
        result: tuple[list[PlaylistItem], int] | list[PlaylistItem],
        *,
        announce: bool,
    ) -> None:
        _finalize_folder_load_impl(
            self,
            playlist_id,
            folder_path,
            result,
            announce=announce,
        )

    def _handle_folder_preview(self, playlist_id: str, item_id: str) -> None:
        _handle_folder_preview_impl(self, playlist_id, item_id)

    def _stop_preview(self) -> None:
        _stop_preview_impl(self)

    def _send_folder_items_to_music(self, playlist_id: str, item_ids: Sequence[str]) -> None:
        _send_folder_items_to_music_impl(self, playlist_id, item_ids)

    def _target_music_playlist(self) -> tuple[PlaylistPanel, PlaylistModel] | None:
        return _target_music_playlist_impl(self)

    def _refresh_news_panels(self) -> None:
        _refresh_news_panels_impl(self)

    def _active_news_panel(self) -> tuple[NewsPlaylistPanel | None, wx.Window | None]:
        return _active_news_panel_impl(self)

    def _focused_playlist_id(self) -> str | None:
        return _focused_playlist_id_impl(self)

    def _focus_playlist_panel(self, playlist_id: str) -> bool:
        return _focus_playlist_panel_impl(self, playlist_id)

    def _cycle_playlist_focus(self, *, backwards: bool) -> bool:
        return _cycle_playlist_focus_impl(self, backwards=backwards)

    def _on_playlist_selection_change(self, playlist_id: str, indices: list[int]) -> None:
        _on_playlist_selection_change_impl(self, playlist_id, indices)

    def _on_playlist_play_request(self, playlist_id: str, item_id: str) -> None:
        self._play_item_direct(playlist_id, item_id)

    def _play_item_direct(self, playlist_id: str, item_id: str) -> bool:
        panel = self._playlists.get(playlist_id)
        playlist = self._get_playlist_model(playlist_id)
        if not isinstance(panel, PlaylistPanel) or playlist is None:
            return False
        if self._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC:
            return self._auto_mix_play_next(panel)
        # Tryb ręczny: jeśli jest ustawiona kolejka (zaznaczenia), ma ona zawsze priorytet nad wskazanym/podświetlonym.
        if not self._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC and self._playlist_has_selection(playlist_id):
            return self._start_next_from_playlist(panel, ignore_ui_selection=True, advance_focus=False)
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
        return _prompt_new_playlist_impl(self)

    def _on_add_tracks(self, event: wx.CommandEvent) -> None:
        _on_add_tracks_impl(self, event)

    def _finalize_add_tracks(self, panel: PlaylistPanel, new_items: list[PlaylistItem]) -> None:
        _finalize_add_tracks_impl(self, panel, new_items)

    def _on_remove_playlist(self, _event: wx.CommandEvent) -> None:
        _on_remove_playlist_impl(self, _event)

    def _on_manage_playlists(self, _event: wx.CommandEvent) -> None:
        _on_manage_playlists_impl(self, _event)

    def _on_assign_device(self, _event: wx.CommandEvent) -> None:
        _on_assign_device_impl(self, _event)

    def _configure_playlist_devices(self, playlist_id: str) -> list[str | None] | None:
        return _configure_playlist_devices_impl(self, playlist_id)

    def _on_import_playlist(self, event: wx.CommandEvent) -> None:
        _on_import_playlist_impl(self, event)

    def _parse_m3u(self, path: Path) -> list[dict[str, Any]]:
        return _parse_m3u_impl(path)

    def _on_export_playlist(self, _event: wx.CommandEvent) -> None:
        _on_export_playlist_impl(self, _event)

    def _on_exit(self, event: wx.CommandEvent) -> None:
        try:
            self._audio_engine.stop_all()
        finally:
            self.Close()

    def _on_close(self, event: wx.CloseEvent) -> None:
        try:
            self._jingles.stop_all()
        except Exception:
            pass
        event.Skip()

    def _on_options(self, event: wx.CommandEvent) -> None:
        _on_options_impl(self, event)

    def _on_edit_shortcuts(self, _event: wx.CommandEvent) -> None:
        _on_edit_shortcuts_impl(self, _event)

    def _on_jingles(self, _event: wx.CommandEvent) -> None:
        _on_jingles_impl(self, _event)

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
        _on_toggle_loop_playback_impl(self, _event)

    def _apply_replay_gain(self, item: PlaylistItem, gain_db: float | None) -> None:
        item.replay_gain_db = gain_db
        if not save_replay_gain_metadata(item.path, gain_db):
            self._announce_event("pfl", _("Failed to update ReplayGain metadata"))
        else:
            self._announce_event("pfl", _("Updated ReplayGain for %s") % item.title)

    def _on_loop_info(self, _event: wx.CommandEvent) -> None:
        _on_loop_info_impl(self, _event)

    def _on_track_remaining(self, _event: wx.CommandEvent | None = None) -> None:
        _on_track_remaining_impl(self, _event)

    def _apply_loop_setting_to_playback(self, *, playlist_id: str | None = None, item_id: str | None = None) -> None:
        _apply_loop_setting_to_playback_impl(self, playlist_id=playlist_id, item_id=item_id)

    def _sync_loop_mix_trigger(
        self,
        *,
        panel: PlaylistPanel | None,
        playlist: PlaylistModel,
        item: PlaylistItem,
        context: PlaybackContext,
    ) -> None:
        _sync_loop_mix_trigger_impl(self, panel=panel, playlist=playlist, item=item, context=context)

    def _apply_mix_trigger_to_playback(self, *, playlist_id: str, item: PlaylistItem, panel: PlaylistPanel) -> None:
        _apply_mix_trigger_to_playback_impl(
            self,
            playlist_id=playlist_id,
            item=item,
            panel=panel,
            call_after=wx.CallAfter,
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
        return _auto_mix_play_next_impl(self, panel)

    def _on_mix_points_configure(self, playlist_id: str, item_id: str) -> None:
        _on_mix_points_configure_impl(self, playlist_id, item_id)

    def _propagate_mix_points_for_path(
        self,
        *,
        path: Path,
        mix_values: dict[str, float | None],
        source_playlist_id: str,
        source_item_id: str,
    ) -> None:
        _propagate_mix_points_for_path_impl(
            self,
            path=path,
            mix_values=mix_values,
            source_playlist_id=source_playlist_id,
            source_item_id=source_item_id,
        )

    def _start_playback(
        self,
        panel: PlaylistPanel,
        item: PlaylistItem,
        *,
        restart_playing: bool = False,
        auto_mix_sequence: bool = False,
        prefer_overlap: bool = False,
    ) -> bool:
        return _start_playback_impl(
            self,
            panel,
            item,
            restart_playing=restart_playing,
            auto_mix_sequence=auto_mix_sequence,
            prefer_overlap=prefer_overlap,
        )

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
        return _start_next_from_playlist_impl(
            self,
            panel,
            ignore_ui_selection=ignore_ui_selection,
            advance_focus=advance_focus,
            restart_playing=restart_playing,
            force_automix_sequence=force_automix_sequence,
            prefer_overlap=prefer_overlap,
        )

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
        _handle_playback_finished_impl(self, playlist_id, item_id)

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
        _auto_mix_state_process_impl(self, panel, item, context_entry, seconds, queued_selection)

    def _auto_mix_now_from_callback(self, playlist_id: str, item_id: str) -> None:
        playlist = self._get_playlist_model(playlist_id)
        if not playlist:
            return
        panel = self._playlists.get(playlist_id)
        if not panel:
            return
        item = playlist.get_item(item_id)
        if not item:
            return
        try:
            self._auto_mix_now(playlist, item, panel)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("UI: auto_mix_now callback failed playlist=%s item=%s err=%s", playlist_id, item_id, exc)

    def _auto_mix_now(self, playlist: PlaylistModel, item: PlaylistItem, panel: PlaylistPanel) -> None:
        _auto_mix_now_impl(self, playlist, item, panel)

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
        _handle_playlist_hotkey_impl(self, event)
    def _get_current_playlist_panel(self):
        return _get_current_playlist_panel_impl(self)

    def _get_audio_panel(self, kinds: tuple[PlaylistKind, ...]) -> PlaylistPanel | None:
        panel = self._get_current_playlist_panel()
        if isinstance(panel, PlaylistPanel) and panel.model.kind in kinds:
            return panel
        return None

    def _get_current_music_panel(self) -> PlaylistPanel | None:
        return self._get_audio_panel((PlaylistKind.MUSIC,))

    def _handle_focus_click(self, event: wx.MouseEvent, playlist_id: str) -> None:
        _handle_focus_click_impl(self, event, playlist_id)

    def _on_playlist_focus(self, playlist_id: str) -> None:
        _on_playlist_focus_impl(self, playlist_id)

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
        return _collect_files_from_paths_impl(paths)

    def _metadata_worker_count(self, total: int) -> int:
        return _metadata_worker_count_impl(total)

    def _build_playlist_item(
        self,
        path: Path,
        metadata: AudioMetadata,
        *,
        override_title: str | None = None,
        override_artist: str | None = None,
        override_duration: float | None = None,
    ) -> PlaylistItem:
        return _build_playlist_item_impl(
            self,
            path,
            metadata,
            override_title=override_title,
            override_artist=override_artist,
            override_duration=override_duration,
        )

    def _load_playlist_item(
        self,
        path: Path,
        entry: dict[str, Any] | None = None,
    ) -> PlaylistItem | None:
        return _load_playlist_item_impl(self, path, entry)

    def _create_items_from_paths(self, file_paths: list[Path]) -> list[PlaylistItem]:
        return _create_items_from_paths_impl(self, file_paths)

    def _run_item_loader(
        self,
        *,
        description: str,
        worker: Callable[[], list[PlaylistItem]],
        on_complete: Callable[[list[PlaylistItem]], None],
    ) -> None:
        _run_item_loader_impl(self, description=description, worker=worker, on_complete=on_complete)

    def _create_items_from_m3u_entries(self, entries: list[dict[str, Any]]) -> list[PlaylistItem]:
        return _create_items_from_m3u_entries_impl(self, entries)

    def _load_items_from_sources(
        self,
        sources: list[tuple[Path, dict[str, Any] | None]],
    ) -> list[PlaylistItem]:
        return _load_items_from_sources_impl(self, sources)

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
        _maybe_focus_playing_item_impl(self, panel, item_id)

    def _resolve_remaining_playback(self) -> tuple[PlaylistModel, PlaylistItem, float] | None:
        return _resolve_remaining_playback_impl(self)

    def _active_playlist_item(self, playlist: PlaylistModel) -> PlaylistItem | None:
        return _active_playlist_item_impl(self, playlist)

    def _compute_intro_remaining(self, item: PlaylistItem, absolute_seconds: float | None = None) -> float | None:
        return _compute_intro_remaining_impl(item, absolute_seconds)

    def _announce_intro_remaining(self, remaining: float, *, prefix_only: bool = False) -> None:
        _announce_intro_remaining_impl(self, remaining, prefix_only=prefix_only)

    def _announce_track_end_remaining(self, remaining: float) -> None:
        _announce_track_end_remaining_impl(self, remaining)

    def _cleanup_intro_alert_player(self, player: Player) -> None:
        _cleanup_intro_alert_player_impl(self, player)

    def _play_intro_alert(self) -> bool:
        return _play_intro_alert_impl(self)

    def _cleanup_track_end_alert_player(self, player: Player) -> None:
        _cleanup_track_end_alert_player_impl(self, player)

    def _play_track_end_alert(self) -> bool:
        return _play_track_end_alert_impl(self)

    def _consider_intro_alert(
        self,
        panel: PlaylistPanel,
        item: PlaylistItem,
        context: PlaybackContext,
        absolute_seconds: float,
    ) -> None:
        _consider_intro_alert_impl(self, panel, item, context, absolute_seconds)

    def _consider_track_end_alert(
        self,
        _panel: PlaylistPanel,
        item: PlaylistItem,
        context: PlaybackContext,
    ) -> None:
        _consider_track_end_alert_impl(self, _panel, item, context)

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
        _push_undo_action_impl(self, model, operation)

    def _apply_undo_callback(self, action: UndoAction, reverse: bool) -> bool:
        return _apply_undo_callback_impl(self, action, reverse)

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
        _on_copy_selection_impl(self, _event)

    def _on_cut_selection(self, _event: wx.CommandEvent) -> None:
        _on_cut_selection_impl(self, _event)

    def _on_paste_selection(self, _event: wx.CommandEvent) -> None:
        _on_paste_selection_impl(self, _event)

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
        _finalize_clipboard_paste_impl(
            self,
            panel,
            model,
            items,
            insert_at,
            anchor_index,
            skipped_files=skipped_files,
        )

    def _on_delete_selection(self, _event: wx.CommandEvent) -> None:
        _on_delete_selection_impl(self, _event)

    def _move_selection(self, delta: int) -> None:
        _move_selection_impl(self, delta)

    def _on_move_selection_up(self, _event: wx.CommandEvent) -> None:
        self._move_selection(-1)

    def _on_move_selection_down(self, _event: wx.CommandEvent) -> None:
        self._move_selection(1)

    def _on_undo(self, _event: wx.CommandEvent) -> None:
        _on_undo_impl(self, _event)

    def _on_redo(self, _event: wx.CommandEvent) -> None:
        _on_redo_impl(self, _event)

    def _update_active_playlist_styles(self) -> None:
        _update_active_playlist_styles_impl(self)

    def _get_playback_context(self, playlist_id: str) -> tuple[tuple[str, str], PlaybackContext] | None:
        return _get_playback_context_impl(self, playlist_id)

    def _get_playing_item_id(self, playlist_id: str) -> str | None:
        return _get_playing_item_id_impl(self, playlist_id)

    def _get_busy_device_ids(self) -> set[str]:
        return _get_busy_device_ids_impl(self)

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
        _stop_playlist_playback_impl(self, playlist_id, mark_played=mark_played, fade_duration=fade_duration)

    def _cancel_active_playback(self, playlist_id: str, mark_played: bool = False) -> None:
        _cancel_active_playback_impl(self, playlist_id, mark_played=mark_played)

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
        return _supports_mix_trigger_impl(self, player)

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
        _register_mix_plan_impl(
            self._mix_plans,
            self._mix_trigger_points,
            playlist_id,
            item_id,
            mix_at=mix_at,
            fade_seconds=fade_seconds,
            base_cue=base_cue,
            effective_duration=effective_duration,
            native_trigger=native_trigger,
        )

    def _clear_mix_plan(self, playlist_id: str, item_id: str) -> None:
        _clear_mix_plan_impl(self._mix_plans, self._mix_trigger_points, playlist_id, item_id)

    def _mark_mix_triggered(self, playlist_id: str, item_id: str) -> None:
        _mark_mix_triggered_impl(self._mix_plans, playlist_id, item_id)

    def _resolve_mix_timing(
        self,
        item: PlaylistItem,
        overrides: dict[str, float | None] | None = None,
        *,
        effective_duration_override: float | None = None,
    ) -> tuple[float | None, float, float, float]:
        """Return (mix_at_seconds, fade_seconds, base_cue, effective_duration) using optional overrides."""
        overrides = dict(overrides or {})
        overrides.pop("_preview_pre_seconds", None)
        return _resolve_mix_timing_impl(
            item,
            self._fade_duration,
            overrides,
            effective_duration_override=effective_duration_override,
        )

    def _measure_effective_duration(self, playlist: PlaylistModel, item: PlaylistItem) -> float | None:
        return _measure_effective_duration_impl(self, playlist, item)

    def _compute_mix_trigger_seconds(self, item: PlaylistItem) -> float | None:
        """Calculate absolute time (seconds) to trigger automix/crossfade."""
        return _compute_mix_trigger_seconds_impl(item, self._fade_duration)

    def _preview_mix_with_next(
        self,
        playlist: PlaylistModel,
        item: PlaylistItem,
        *,
        overrides: dict[str, Optional[float]] | None = None,
    ) -> bool:
        return _preview_mix_with_next_impl(self, playlist, item, overrides=overrides)
