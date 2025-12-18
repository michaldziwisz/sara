"""Main window of the SARA application."""

from __future__ import annotations

import logging
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
from sara.ui.playlist_layout import PlaylistLayoutManager
from sara.ui.announcement_service import AnnouncementService
from sara.ui.playback_controller import PlaybackContext, PlaybackController
from sara.ui.auto_mix_tracker import AutoMixTracker
from sara.ui.clipboard_service import PlaylistClipboard
from sara.ui.jingle_controller import JingleController
from sara.ui.controllers.playback_flow import (
    handle_playback_finished as _handle_playback_finished_impl,
    play_item_direct as _play_item_direct_impl,
    start_next_from_playlist as _start_next_from_playlist_impl,
    start_playback as _start_playback_impl,
)
from sara.ui.controllers.playback_navigation import (
    adjust_duration_and_mix_trigger as _adjust_duration_and_mix_trigger_impl,
    derive_next_play_index as _derive_next_play_index_impl,
    handle_playback_progress as _handle_playback_progress_impl,
    index_of_item as _index_of_item_impl,
    manual_fade_duration as _manual_fade_duration_impl,
    on_global_play_next as _on_global_play_next_impl,
    play_next_alternate as _play_next_alternate_impl,
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
    set_auto_mix_enabled as _set_auto_mix_enabled_impl,
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
    on_toggle_selection as _on_toggle_selection_impl,
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
from sara.ui.controllers.playlist_mutations import (
    remove_item_from_playlist as _remove_item_from_playlist_impl,
    remove_items as _remove_items_impl,
)
from sara.ui.controllers.playlist_selection import (
    get_selected_context as _get_selected_context_impl,
    get_selected_items as _get_selected_items_impl,
)
from sara.ui.controllers.clipboard_helpers import (
    create_item_from_serialized as _create_item_from_serialized_impl,
    get_system_clipboard_paths as _get_system_clipboard_paths_impl,
    serialize_items as _serialize_items_impl,
    set_system_clipboard_paths as _set_system_clipboard_paths_impl,
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
    handle_global_char_hook as _handle_global_char_hook_impl,
    update_shortcut_menu_labels as _update_shortcut_menu_labels_impl,
)
from sara.ui.controllers.news_audio import (
    news_device_entries as _news_device_entries_impl,
    play_news_audio_clip as _play_news_audio_clip_impl,
    preview_news_clip as _preview_news_clip_impl,
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
        self._init_settings(settings)
        self._init_playlist_state(state)
        self._init_audio_controllers()
        self._init_command_ids()
        self._init_runtime_state()
        self._ensure_legacy_hooks()
        self._init_ui()

    def _init_settings(self, settings: SettingsManager | None) -> None:
        self._settings = settings or SettingsManager()
        set_language(self._settings.get_language())
        if not self._settings.config_path.exists():
            self._settings.save()

    def _init_playlist_state(self, state: AppState | None) -> None:
        self._playlists: Dict[str, PlaylistPanel] = {}
        self._playlist_wrappers: Dict[str, wx.Window] = {}
        self._playlist_headers: Dict[str, wx.StaticText] = {}
        self._playlist_titles: Dict[str, str] = {}
        self._layout = PlaylistLayoutManager()
        self._current_index: int = 0
        self._state = state or AppState()
        self._playlist_factory = PlaylistFactory()

    def _init_audio_controllers(self) -> None:
        self._audio_engine = AudioEngine()
        self._playback = PlaybackController(self._audio_engine, self._settings, self._announce_event)
        self._jingles_path = self._settings.config_path.parent / "jingles.sarajingles"
        self._jingles = JingleController(
            self._audio_engine,
            self._settings,
            self._announce_event,
            set_path=self._jingles_path,
        )

    def _init_command_ids(self) -> None:
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

    def _init_runtime_state(self) -> None:
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
        self._mix_trigger_points: Dict[
            tuple[str, str], float
        ] = {}  # (playlist_id, item_id) -> absolute mix_at seconds
        self._mix_plans: Dict[tuple[str, str], MixPlan] = {}
        self._auto_mix_tracker = AutoMixTracker()  # wirtualny kursor automix niezależny od UI
        self._auto_mix_busy: Dict[str, bool] = {}  # blokada reentrancji per playlist
        self._last_focus_index: Dict[str, int] = {}

    def _init_ui(self) -> None:
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

    def _update_shortcut_menu_labels(self) -> None:
        _update_shortcut_menu_labels_impl(self)

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

    def _configure_accelerators(self) -> None:
        _configure_accelerators_impl(self)

    def _handle_global_char_hook(self, event: wx.KeyEvent) -> None:
        _handle_global_char_hook_impl(self, event)

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

    def _news_device_entries(self) -> list[tuple[str | None, str]]:
        return _news_device_entries_impl(self)

    def _play_news_audio_clip(self, model: PlaylistModel, clip_path: Path, device_id: str | None) -> None:
        _play_news_audio_clip_impl(self, model, clip_path, device_id)

    def _preview_news_clip(self, clip_path: Path) -> bool:
        return _preview_news_clip_impl(self, clip_path)

    def _persist_playlist_outputs(self, model: PlaylistModel) -> None:
        self._settings.set_playlist_outputs(model.name, model.get_configured_slots())
        self._settings.save()

    def _select_folder_for_playlist(self, playlist_id: str) -> None:
        _select_folder_for_playlist_impl(self, playlist_id)

    def _reload_folder_playlist(self, playlist_id: str) -> None:
        _reload_folder_playlist_impl(self, playlist_id)

    def _load_folder_playlist(self, playlist: PlaylistModel, *, announce: bool = True) -> None:
        _load_folder_playlist_impl(self, playlist, announce=announce)

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
        return _play_item_direct_impl(self, playlist_id, item_id, panel_type=PlaylistPanel)

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
        _set_auto_mix_enabled_impl(self, enabled, reason=reason)

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
        _on_toggle_selection_impl(self, playlist_id, item_id)

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
        _adjust_duration_and_mix_trigger_impl(self, panel, playlist, item, context)

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
        return _derive_next_play_index_impl(self, playlist)

    @staticmethod
    def _index_of_item(playlist: PlaylistModel, item_id: str | None) -> int | None:
        return _index_of_item_impl(playlist, item_id)

    def _play_next_alternate(self) -> bool:
        return _play_next_alternate_impl(self)

    def _on_global_play_next(self, event: wx.CommandEvent) -> None:
        _on_global_play_next_impl(self, event)

    def _handle_playback_finished(self, playlist_id: str, item_id: str) -> None:
        _handle_playback_finished_impl(self, playlist_id, item_id)

    def _handle_playback_progress(self, playlist_id: str, item_id: str, seconds: float) -> None:
        _handle_playback_progress_impl(self, playlist_id, item_id, seconds)

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
        return _manual_fade_duration_impl(self, playlist, item)

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
        return _get_selected_context_impl(self, kinds=kinds)

    def _get_selected_items(
        self,
        *,
        kinds: tuple[PlaylistKind, ...] = (PlaylistKind.MUSIC,),
    ) -> tuple[PlaylistPanel, PlaylistModel, list[tuple[int, PlaylistItem]]] | None:
        return _get_selected_items_impl(self, kinds=kinds)

    def _serialize_items(self, items: List[PlaylistItem]) -> List[Dict[str, Any]]:
        return _serialize_items_impl(items)

    def _create_item_from_serialized(self, data: Dict[str, Any]) -> PlaylistItem:
        return _create_item_from_serialized_impl(self, data)

    def _refresh_playlist_view(self, panel: PlaylistPanel, selection: list[int] | None) -> None:
        if selection is None:
            panel.refresh()
        else:
            panel.refresh(selection)
        panel.focus_list()

    def _get_system_clipboard_paths(self) -> list[Path]:
        return _get_system_clipboard_paths_impl()

    def _set_system_clipboard_paths(self, paths: list[Path]) -> None:
        _set_system_clipboard_paths_impl(paths)

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
        return _remove_item_from_playlist_impl(self, panel, model, index, refocus=refocus)

    def _remove_items(
        self, panel: PlaylistPanel, model: PlaylistModel, indices: list[int]
    ) -> list[PlaylistItem]:
        return _remove_items_impl(self, panel, model, indices)

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
