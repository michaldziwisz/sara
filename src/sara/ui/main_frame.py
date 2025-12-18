"""Main window of the SARA application."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import wx

from sara.audio.engine import Player
from sara.core.app_state import AppState
from sara.core.config import SettingsManager
from sara.core.i18n import gettext as _
from sara.core.hotkeys import HotkeyAction
from sara.core.media_metadata import (
    save_replay_gain_metadata,
)
from sara.core.mix_planner import (
    MixPlan,
    clear_mix_plan as _clear_mix_plan_impl,
    mark_mix_triggered as _mark_mix_triggered_impl,
    register_mix_plan as _register_mix_plan_impl,
    resolve_mix_timing as _resolve_mix_timing_impl,
)
from sara.core.playlist import PlaylistItem, PlaylistKind, PlaylistModel
from sara.core.shortcuts import get_shortcut
from sara.ui.undo import UndoAction
from sara.ui.playlist_panel import PlaylistPanel
from sara.ui.playback_controller import PlaybackContext
from sara.ui.controllers.frame_bootstrap import (
    init_audio_controllers as _init_audio_controllers_impl,
    init_command_ids as _init_command_ids_impl,
    init_playlist_state as _init_playlist_state_impl,
    init_runtime_state as _init_runtime_state_impl,
    init_settings as _init_settings_impl,
    init_ui as _init_ui_impl,
)
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
    preferred_auto_mix_index as _preferred_auto_mix_index_impl,
    set_auto_mix_enabled as _set_auto_mix_enabled_impl,
)
from sara.ui.controllers.playlist_io import (
    on_export_playlist as _on_export_playlist_impl,
    on_import_playlist as _on_import_playlist_impl,
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
    handle_folder_preview as _handle_folder_preview_impl,
    load_folder_playlist as _load_folder_playlist_impl,
    reload_folder_playlist as _reload_folder_playlist_impl,
    select_folder_for_playlist as _select_folder_for_playlist_impl,
    send_folder_items_to_music as _send_folder_items_to_music_impl,
    stop_preview as _stop_preview_impl,
)
from sara.ui.controllers.item_loading import (
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
    auto_mix_now_from_callback as _auto_mix_now_from_callback_impl,
    auto_mix_now as _auto_mix_now_impl,
    auto_mix_state_process as _auto_mix_state_process_impl,
)


class MainFrame(wx.Frame):
    """Main window managing playlists and global shortcuts."""

    TITLE = "SARA"

    _init_settings = _init_settings_impl
    _init_playlist_state = _init_playlist_state_impl
    _init_audio_controllers = _init_audio_controllers_impl
    _init_command_ids = _init_command_ids_impl
    _init_runtime_state = _init_runtime_state_impl
    _init_ui = _init_ui_impl
    _create_menu_bar = _create_menu_bar_impl
    _update_shortcut_menu_labels = _update_shortcut_menu_labels_impl
    _create_ui = _create_ui_impl
    _configure_accelerators = _configure_accelerators_impl
    _handle_global_char_hook = _handle_global_char_hook_impl
    add_playlist = _add_playlist_impl
    _apply_playlist_order = _apply_playlist_order_impl
    _remove_playlist_by_id = _remove_playlist_by_id_impl
    _news_device_entries = _news_device_entries_impl
    _play_news_audio_clip = _play_news_audio_clip_impl
    _preview_news_clip = _preview_news_clip_impl
    _select_folder_for_playlist = _select_folder_for_playlist_impl
    _reload_folder_playlist = _reload_folder_playlist_impl
    _load_folder_playlist = _load_folder_playlist_impl
    _handle_folder_preview = _handle_folder_preview_impl
    _stop_preview = _stop_preview_impl
    _send_folder_items_to_music = _send_folder_items_to_music_impl
    _refresh_news_panels = _refresh_news_panels_impl
    _active_news_panel = _active_news_panel_impl
    _focused_playlist_id = _focused_playlist_id_impl
    _focus_playlist_panel = _focus_playlist_panel_impl
    _cycle_playlist_focus = _cycle_playlist_focus_impl
    _on_playlist_selection_change = _on_playlist_selection_change_impl
    _prompt_new_playlist = _prompt_new_playlist_impl
    _on_add_tracks = _on_add_tracks_impl
    _finalize_add_tracks = _finalize_add_tracks_impl
    _on_remove_playlist = _on_remove_playlist_impl
    _on_manage_playlists = _on_manage_playlists_impl
    _on_assign_device = _on_assign_device_impl
    _configure_playlist_devices = _configure_playlist_devices_impl
    _on_import_playlist = _on_import_playlist_impl
    _on_export_playlist = _on_export_playlist_impl
    _on_options = _on_options_impl
    _on_edit_shortcuts = _on_edit_shortcuts_impl
    _on_jingles = _on_jingles_impl
    _set_auto_mix_enabled = _set_auto_mix_enabled_impl
    _preferred_auto_mix_index = staticmethod(_preferred_auto_mix_index_impl)
    _on_toggle_loop_playback = _on_toggle_loop_playback_impl
    _on_loop_info = _on_loop_info_impl
    _on_track_remaining = _on_track_remaining_impl
    _apply_loop_setting_to_playback = _apply_loop_setting_to_playback_impl
    _sync_loop_mix_trigger = _sync_loop_mix_trigger_impl
    _on_toggle_selection = _on_toggle_selection_impl
    _auto_mix_play_next = _auto_mix_play_next_impl
    _on_mix_points_configure = _on_mix_points_configure_impl
    _adjust_duration_and_mix_trigger = _adjust_duration_and_mix_trigger_impl
    _derive_next_play_index = _derive_next_play_index_impl
    _index_of_item = staticmethod(_index_of_item_impl)
    _play_next_alternate = _play_next_alternate_impl
    _on_global_play_next = _on_global_play_next_impl
    _handle_playback_finished = _handle_playback_finished_impl
    _handle_playback_progress = _handle_playback_progress_impl
    _auto_mix_state_process = _auto_mix_state_process_impl
    _auto_mix_now_from_callback = _auto_mix_now_from_callback_impl
    _auto_mix_now = _auto_mix_now_impl
    _manual_fade_duration = _manual_fade_duration_impl
    _on_playlist_hotkey = _handle_playlist_hotkey_impl
    _get_current_playlist_panel = _get_current_playlist_panel_impl
    _handle_focus_click = _handle_focus_click_impl
    _on_playlist_focus = _on_playlist_focus_impl
    _get_selected_context = _get_selected_context_impl
    _get_selected_items = _get_selected_items_impl
    _serialize_items = staticmethod(_serialize_items_impl)
    _create_item_from_serialized = _create_item_from_serialized_impl
    _get_system_clipboard_paths = staticmethod(_get_system_clipboard_paths_impl)
    _set_system_clipboard_paths = staticmethod(_set_system_clipboard_paths_impl)
    _collect_files_from_paths = staticmethod(_collect_files_from_paths_impl)
    _metadata_worker_count = staticmethod(_metadata_worker_count_impl)
    _load_playlist_item = _load_playlist_item_impl
    _create_items_from_paths = _create_items_from_paths_impl
    _run_item_loader = _run_item_loader_impl
    _create_items_from_m3u_entries = _create_items_from_m3u_entries_impl
    _load_items_from_sources = _load_items_from_sources_impl
    _maybe_focus_playing_item = _maybe_focus_playing_item_impl
    _resolve_remaining_playback = _resolve_remaining_playback_impl
    _active_playlist_item = _active_playlist_item_impl
    _compute_intro_remaining = staticmethod(_compute_intro_remaining_impl)
    _announce_intro_remaining = _announce_intro_remaining_impl
    _announce_track_end_remaining = _announce_track_end_remaining_impl
    _cleanup_intro_alert_player = _cleanup_intro_alert_player_impl
    _play_intro_alert = _play_intro_alert_impl
    _cleanup_track_end_alert_player = _cleanup_track_end_alert_player_impl
    _play_track_end_alert = _play_track_end_alert_impl
    _consider_intro_alert = _consider_intro_alert_impl
    _consider_track_end_alert = _consider_track_end_alert_impl
    _remove_item_from_playlist = _remove_item_from_playlist_impl
    _remove_items = _remove_items_impl
    _push_undo_action = _push_undo_action_impl
    _apply_undo_callback = _apply_undo_callback_impl
    _on_copy_selection = _on_copy_selection_impl
    _on_cut_selection = _on_cut_selection_impl
    _on_paste_selection = _on_paste_selection_impl
    _on_delete_selection = _on_delete_selection_impl
    _move_selection = _move_selection_impl
    _on_undo = _on_undo_impl
    _on_redo = _on_redo_impl
    _update_active_playlist_styles = _update_active_playlist_styles_impl
    _get_playback_context = _get_playback_context_impl
    _get_playing_item_id = _get_playing_item_id_impl
    _stop_playlist_playback = _stop_playlist_playback_impl
    _supports_mix_trigger = _supports_mix_trigger_impl
    _measure_effective_duration = _measure_effective_duration_impl
    _preview_mix_with_next = _preview_mix_with_next_impl

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

    def _register_accessibility(self) -> None:
        # Placeholder: konfiguracje wx.Accessible zostaną dodane w przyszłych iteracjach
        pass

    def _get_playlist_model(self, playlist_id: str) -> PlaylistModel | None:
        return self._state.playlists.get(playlist_id)

    def _playlist_has_selection(self, playlist_id: str) -> bool:
        model = self._get_playlist_model(playlist_id)
        if not model:
            return False
        return any(item.is_selected for item in model.items)

    @staticmethod
    def _format_track_name(item: PlaylistItem) -> str:
        return f"{item.artist} - {item.title}" if item.artist else item.title

    def _persist_playlist_outputs(self, model: PlaylistModel) -> None:
        self._settings.set_playlist_outputs(model.name, model.get_configured_slots())
        self._settings.save()


    def _on_playlist_play_request(self, playlist_id: str, item_id: str) -> None:
        self._play_item_direct(playlist_id, item_id)

    def _play_item_direct(self, playlist_id: str, item_id: str) -> bool:
        return _play_item_direct_impl(self, playlist_id, item_id, panel_type=PlaylistPanel)


    def _on_new_playlist(self, event: wx.CommandEvent) -> None:
        self._create_playlist_dialog(event)

    def _create_playlist_dialog(self, _event: wx.CommandEvent) -> None:
        self._prompt_new_playlist()

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

    def _on_toggle_auto_mix(self, event: wx.CommandEvent) -> None:
        self._set_auto_mix_enabled(not self._auto_mix_enabled)

    def _apply_replay_gain(self, item: PlaylistItem, gain_db: float | None) -> None:
        item.replay_gain_db = gain_db
        if not save_replay_gain_metadata(item.path, gain_db):
            self._announce_event("pfl", _("Failed to update ReplayGain metadata"))
        else:
            self._announce_event("pfl", _("Updated ReplayGain for %s") % item.title)


    def _apply_mix_trigger_to_playback(self, *, playlist_id: str, item: PlaylistItem, panel: PlaylistPanel) -> None:
        _apply_mix_trigger_to_playback_impl(
            self,
            playlist_id=playlist_id,
            item=item,
            panel=panel,
            call_after=wx.CallAfter,
        )


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


    def _get_audio_panel(self, kinds: tuple[PlaylistKind, ...]) -> PlaylistPanel | None:
        panel = self._get_current_playlist_panel()
        if isinstance(panel, PlaylistPanel) and panel.model.kind in kinds:
            return panel
        return None

    def _get_current_music_panel(self) -> PlaylistPanel | None:
        return self._get_audio_panel((PlaylistKind.MUSIC,))


    def _refresh_playlist_view(self, panel: PlaylistPanel, selection: list[int] | None) -> None:
        if selection is None:
            panel.refresh()
        else:
            panel.refresh(selection)
        panel.focus_list()


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




    def _forget_last_started_item(self, playlist_id: str, item_id: str) -> None:
        if self._last_started_item_id.get(playlist_id) == item_id:
            self._last_started_item_id[playlist_id] = None


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


    def _on_move_selection_up(self, _event: wx.CommandEvent) -> None:
        self._move_selection(-1)

    def _on_move_selection_down(self, _event: wx.CommandEvent) -> None:
        self._move_selection(1)


    def _refresh_selection_display(self, playlist_id: str) -> None:
        panel = self._playlists.get(playlist_id)
        if panel:
            panel.refresh()


    def _announce_event(
        self,
        category: str,
        message: str,
        *,
        spoken_message: str | None = None,
    ) -> None:
        """Announce `message` and optionally override spoken content."""
        self._announcer.announce(category, message, spoken_message=spoken_message)

    def _announce(self, message: str) -> None:
        self._announce_event("general", message)


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
