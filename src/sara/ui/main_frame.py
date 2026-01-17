"""Main window of the SARA application."""

from __future__ import annotations

import wx

from sara.core.app_state import AppState
from sara.core.config import SettingsManager
from sara.core.i18n import gettext as _
from sara.core.hotkeys import HotkeyAction
from sara.core.media_metadata import save_replay_gain_metadata
from sara.core.mix_planner import (
    clear_mix_plan as _clear_mix_plan_impl,
    mark_mix_triggered as _mark_mix_triggered_impl,
    register_mix_plan as _register_mix_plan_impl,
    resolve_mix_timing as _resolve_mix_timing_impl,
)
from sara.core.playlist import PlaylistItem, PlaylistKind, PlaylistModel
from sara.core.shortcuts import get_shortcut
from sara.ui import mix_preview as _mix_preview
from sara.ui import mix_runtime as _mix_runtime
from sara.ui.playlist_panel import PlaylistPanel
from sara.ui.controllers import alerts as _alerts
from sara.ui.controllers import automix_flow as _automix_flow
from sara.ui.controllers import clipboard_helpers as _clipboard_helpers
from sara.ui.controllers import edit_actions as _edit_actions
from sara.ui.controllers import folder_playlists as _folder_playlists
from sara.ui.controllers import frame_bootstrap as _frame_bootstrap
from sara.ui.controllers import item_loading as _item_loading
from sara.ui.controllers import loop_and_remaining as _loop_and_remaining
from sara.ui.controllers import menu_and_shortcuts as _menu_and_shortcuts
from sara.ui.controllers import mix_points_controller as _mix_points_controller
from sara.ui.controllers import news_audio as _news_audio
from sara.ui.controllers import playback_flow as _playback_flow
from sara.ui.controllers import playback_navigation as _playback_navigation
from sara.ui.controllers import playback_state as _playback_state
from sara.ui.controllers import playlist_focus as _playlist_focus
from sara.ui.controllers import playlist_hotkeys as _playlist_hotkeys
from sara.ui.controllers import playlist_io as _playlist_io
from sara.ui.controllers import playlist_mutations as _playlist_mutations
from sara.ui.controllers import playlist_selection as _playlist_selection
from sara.ui.controllers import playlists_management as _playlists_management
from sara.ui.controllers import playlists_ui as _playlists_ui
from sara.ui.controllers import tools_dialogs as _tools_dialogs
from sara.ui.controllers.playlists import item_types as _item_types


class MainFrame(wx.Frame):
    """Main window managing playlists and global shortcuts."""

    TITLE = "SARA"

    _init_settings = _frame_bootstrap.init_settings
    _init_playlist_state = _frame_bootstrap.init_playlist_state
    _init_audio_controllers = _frame_bootstrap.init_audio_controllers
    _init_command_ids = _frame_bootstrap.init_command_ids
    _init_runtime_state = _frame_bootstrap.init_runtime_state
    _init_ui = _frame_bootstrap.init_ui

    _create_menu_bar = _menu_and_shortcuts.create_menu_bar
    _update_shortcut_menu_labels = _menu_and_shortcuts.update_shortcut_menu_labels
    _configure_accelerators = _menu_and_shortcuts.configure_accelerators
    _handle_global_char_hook = _menu_and_shortcuts.handle_global_char_hook

    _create_ui = _playlists_ui.create_ui
    add_playlist = _playlists_ui.add_playlist
    _apply_playlist_order = _playlists_ui.apply_playlist_order
    _remove_playlist_by_id = _playlists_ui.remove_playlist_by_id

    _news_device_entries = _news_audio.news_device_entries
    _play_news_audio_clip = _news_audio.play_news_audio_clip
    _preview_news_clip = _news_audio.preview_news_clip

    _select_folder_for_playlist = _folder_playlists.select_folder_for_playlist
    _reload_folder_playlist = _folder_playlists.reload_folder_playlist
    _load_folder_playlist = _folder_playlists.load_folder_playlist
    _handle_folder_preview = _folder_playlists.handle_folder_preview
    _stop_preview = _folder_playlists.stop_preview
    _send_folder_items_to_music = _folder_playlists.send_folder_items_to_music

    _refresh_news_panels = _playlist_focus.refresh_news_panels
    _active_news_panel = _playlist_focus.active_news_panel
    _focused_playlist_id = _playlist_focus.focused_playlist_id
    _focus_playlist_panel = _playlist_focus.focus_playlist_panel
    _cycle_playlist_focus = _playlist_focus.cycle_playlist_focus
    _on_playlist_selection_change = _playlist_focus.on_playlist_selection_change
    _handle_focus_click = _playlist_focus.handle_focus_click
    _on_playlist_focus = _playlist_focus.on_playlist_focus
    _on_toggle_selection = _playlist_focus.on_toggle_selection
    _maybe_focus_playing_item = _playlist_focus.maybe_focus_playing_item
    _get_current_playlist_panel = _playlist_focus.get_current_playlist_panel
    _update_active_playlist_styles = _playlist_focus.update_active_playlist_styles

    _on_playlist_hotkey = _playlist_hotkeys.handle_playlist_hotkey
    _get_selected_context = _playlist_selection.get_selected_context
    _get_selected_items = _playlist_selection.get_selected_items

    _configure_playlist_devices = _playlists_management.configure_playlist_devices
    _finalize_add_tracks = _playlists_management.finalize_add_tracks
    _on_add_tracks = _playlists_management.on_add_tracks
    _on_assign_device = _playlists_management.on_assign_device
    _on_manage_playlists = _playlists_management.on_manage_playlists
    _on_remove_playlist = _playlists_management.on_remove_playlist
    _prompt_new_playlist = _playlists_management.prompt_new_playlist

    _on_import_playlist = _playlist_io.on_import_playlist
    _on_export_playlist = _playlist_io.on_export_playlist

    _on_edit_shortcuts = _tools_dialogs.on_edit_shortcuts
    _on_jingles = _tools_dialogs.on_jingles
    _on_options = _tools_dialogs.on_options
    _on_send_feedback = _tools_dialogs.on_send_feedback

    _set_auto_mix_enabled = _automix_flow.set_auto_mix_enabled
    _preferred_auto_mix_index = staticmethod(_automix_flow.preferred_auto_mix_index)
    _auto_mix_play_next = _automix_flow.auto_mix_play_next
    _auto_mix_start_index = _automix_flow.auto_mix_start_index

    _on_mix_points_configure = _mix_points_controller.on_mix_points_configure
    _propagate_mix_points_for_path = _mix_points_controller.propagate_mix_points_for_path

    _adjust_duration_and_mix_trigger = _playback_navigation.adjust_duration_and_mix_trigger
    _derive_next_play_index = _playback_navigation.derive_next_play_index
    _index_of_item = staticmethod(_playback_navigation.index_of_item)
    _play_next_alternate = _playback_navigation.play_next_alternate
    _on_global_play_next = _playback_navigation.on_global_play_next
    _handle_playback_progress = _playback_navigation.handle_playback_progress
    _manual_fade_duration = _playback_navigation.manual_fade_duration

    _handle_playback_finished = _playback_flow.handle_playback_finished
    _start_playback = _playback_flow.start_playback
    _start_next_from_playlist = _playback_flow.start_next_from_playlist

    _get_playback_context = _playback_state.get_playback_context
    _get_playing_item_id = _playback_state.get_playing_item_id
    _stop_playlist_playback = _playback_state.stop_playlist_playback
    _supports_mix_trigger = _playback_state.supports_mix_trigger

    _auto_mix_state_process = _mix_runtime.auto_mix_state_process
    _auto_mix_now_from_callback = _mix_runtime.auto_mix_now_from_callback
    _auto_mix_now = _mix_runtime.auto_mix_now

    _announce_intro_remaining = _alerts.announce_intro_remaining
    _announce_track_end_remaining = _alerts.announce_track_end_remaining
    _cleanup_intro_alert_player = _alerts.cleanup_intro_alert_player
    _cleanup_track_end_alert_player = _alerts.cleanup_track_end_alert_player
    _compute_intro_remaining = staticmethod(_alerts.compute_intro_remaining)
    _consider_intro_alert = _alerts.consider_intro_alert
    _consider_track_end_alert = _alerts.consider_track_end_alert
    _play_intro_alert = _alerts.play_intro_alert
    _play_track_end_alert = _alerts.play_track_end_alert

    _apply_loop_setting_to_playback = _loop_and_remaining.apply_loop_setting_to_playback
    _sync_loop_mix_trigger = _loop_and_remaining.sync_loop_mix_trigger
    _on_loop_info = _loop_and_remaining.on_loop_info
    _on_toggle_loop_playback = _loop_and_remaining.on_toggle_loop_playback
    _on_track_remaining = _loop_and_remaining.on_track_remaining
    _resolve_remaining_playback = _loop_and_remaining.resolve_remaining_playback
    _active_playlist_item = _loop_and_remaining.active_playlist_item

    _serialize_items = staticmethod(_clipboard_helpers.serialize_items)
    _create_item_from_serialized = _clipboard_helpers.create_item_from_serialized
    _get_system_clipboard_paths = staticmethod(_clipboard_helpers.get_system_clipboard_paths)
    _set_system_clipboard_paths = staticmethod(_clipboard_helpers.set_system_clipboard_paths)

    _remove_item_from_playlist = _playlist_mutations.remove_item_from_playlist
    _remove_items = _playlist_mutations.remove_items

    _push_undo_action = _edit_actions.push_undo_action
    _apply_undo_callback = _edit_actions.apply_undo_callback
    _on_copy_selection = _edit_actions.on_copy_selection
    _on_cut_selection = _edit_actions.on_cut_selection
    _on_paste_selection = _edit_actions.on_paste_selection
    _finalize_clipboard_paste = _edit_actions.finalize_clipboard_paste
    _on_delete_selection = _edit_actions.on_delete_selection
    _on_mark_as_song = _item_types.on_mark_as_song
    _on_mark_as_spot = _item_types.on_mark_as_spot
    _move_selection = _edit_actions.move_selection
    _on_undo = _edit_actions.on_undo
    _on_redo = _edit_actions.on_redo

    _collect_files_from_paths = staticmethod(_item_loading.collect_files_from_paths)
    _create_items_from_m3u_entries = _item_loading.create_items_from_m3u_entries
    _create_items_from_paths = _item_loading.create_items_from_paths
    _load_items_from_sources = _item_loading.load_items_from_sources
    _load_playlist_item = _item_loading.load_playlist_item
    _metadata_worker_count = staticmethod(_item_loading.metadata_worker_count)
    _run_item_loader = _item_loading.run_item_loader

    _measure_effective_duration = _mix_preview.measure_effective_duration
    _preview_mix_with_next = _mix_preview.preview_mix_with_next

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
        return _playback_flow.play_item_direct(self, playlist_id, item_id, panel_type=PlaylistPanel)

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
        _mix_runtime.apply_mix_trigger_to_playback(
            self,
            playlist_id=playlist_id,
            item=item,
            panel=panel,
            call_after=wx.CallAfter,
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
