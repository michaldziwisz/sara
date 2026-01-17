"""Okno dialogowe z ustawieniami globalnymi aplikacji."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import wx

from sara.audio.engine import AudioEngine
from sara.core.config import SettingsManager
from sara.core.env import resolve_output_dir
from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistKind
from sara.ui.dialogs.options.accessibility_tab import build_accessibility_tab
from sara.ui.dialogs.options.diagnostics_tab import build_diagnostics_tab
from sara.ui.dialogs.options.general_tab import build_general_tab
from sara.ui.dialogs.options.logging_tab import build_logging_tab
from sara.ui.dialogs.options.startup_playlist_dialog import StartupPlaylistDialog


class OptionsDialog(wx.Dialog):
    """Main application settings window."""

    def __init__(self, parent: wx.Window, *, settings: SettingsManager, audio_engine: AudioEngine) -> None:
        super().__init__(parent, title=_("Options"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetName("options_dialog")
        self._settings = settings
        self._audio_engine = audio_engine

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        self._pfl_entries: list[tuple[Optional[str], str]] = []
        self._announcement_checkboxes: dict[str, wx.CheckBox] = {}
        self._diag_faulthandler_checkbox: Optional[wx.CheckBox] = None
        self._diag_interval_ctrl: Optional[wx.SpinCtrlDouble] = None
        self._diag_loop_checkbox: Optional[wx.CheckBox] = None
        self._diag_log_level_choice: Optional[wx.Choice] = None
        self._played_tracks_logging_checkbox: Optional[wx.CheckBox] = None
        self._played_tracks_logging_folder_ctrl: Optional[wx.TextCtrl] = None
        self._played_tracks_logging_folder_button: Optional[wx.Button] = None
        self._played_tracks_logging_songs_checkbox: Optional[wx.CheckBox] = None
        self._played_tracks_logging_spots_checkbox: Optional[wx.CheckBox] = None
        self._now_playing_checkbox: Optional[wx.CheckBox] = None
        self._now_playing_path_ctrl: Optional[wx.TextCtrl] = None
        self._now_playing_path_button: Optional[wx.Button] = None
        self._now_playing_songs_checkbox: Optional[wx.CheckBox] = None
        self._now_playing_spots_checkbox: Optional[wx.CheckBox] = None
        self._now_playing_on_change_checkbox: Optional[wx.CheckBox] = None
        self._now_playing_periodic_checkbox: Optional[wx.CheckBox] = None
        self._now_playing_interval_ctrl: Optional[wx.SpinCtrl] = None
        self._now_playing_template_ctrl: Optional[wx.TextCtrl] = None

        notebook = wx.Notebook(self)
        main_sizer.Add(notebook, 1, wx.EXPAND | wx.ALL, 10)

        general_panel, add_btn, edit_btn, remove_btn = build_general_tab(self, notebook)
        notebook.AddPage(general_panel, _("General"))

        accessibility_panel = build_accessibility_tab(self, notebook)
        notebook.AddPage(accessibility_panel, _("Accessibility"))

        diag_panel = build_diagnostics_tab(self, notebook)
        notebook.AddPage(diag_panel, _("Diagnostics"))

        logging_panel = build_logging_tab(self, notebook)
        notebook.AddPage(logging_panel, _("Logging"))

        button_sizer = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if button_sizer:
            main_sizer.Add(button_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizer(main_sizer)
        self.SetMinSize((520, 420))

        self._playlists: List[Dict[str, Any]] = self._settings.get_startup_playlists()
        self._refresh_list()
        self._populate_pfl_choice()

        add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        edit_btn.Bind(wx.EVT_BUTTON, self._on_edit)
        remove_btn.Bind(wx.EVT_BUTTON, self._on_remove)
        self.Bind(wx.EVT_BUTTON, self._on_accept, id=wx.ID_OK)

    def _refresh_list(self) -> None:
        self._playlists_list.DeleteAllItems()
        for entry in self._playlists:
            name = entry["name"]
            kind = entry.get("kind", PlaylistKind.MUSIC)
            if not isinstance(kind, PlaylistKind):
                try:
                    kind = PlaylistKind(kind)
                except Exception:
                    kind = PlaylistKind.MUSIC
            index = self._playlists_list.InsertItem(self._playlists_list.GetItemCount(), name)
            if kind is PlaylistKind.MUSIC:
                kind_label = _("Music")
            elif kind is PlaylistKind.NEWS:
                kind_label = _("News")
            else:
                kind_label = _("Music folder")
            self._playlists_list.SetItem(index, 1, kind_label)
            if kind is PlaylistKind.FOLDER:
                players_label = _("PFL")
            else:
                slot_count = sum(1 for slot in entry.get("slots", []) if slot)
                players_label = str(slot_count)
            self._playlists_list.SetItem(index, 2, players_label)
        for column in range(3):
            self._playlists_list.SetColumnWidth(column, wx.LIST_AUTOSIZE_USEHEADER)

    def _selected_index(self) -> int:
        return self._playlists_list.GetFirstSelected()

    def _on_add(self, _event: wx.Event) -> None:
        dialog = StartupPlaylistDialog(self, audio_engine=self._audio_engine)
        if dialog.ShowModal() == wx.ID_OK:
            result = dialog.get_result()
            if result:
                self._playlists.append(result)
                self._refresh_list()
        dialog.Destroy()

    def _on_edit(self, _event: wx.Event) -> None:
        index = self._selected_index()
        if index == wx.NOT_FOUND:
            return
        current = self._playlists[index]
        folder_path = current.get("folder_path")
        if folder_path and not isinstance(folder_path, Path):
            folder_path = Path(folder_path)
        dialog = StartupPlaylistDialog(
            self,
            audio_engine=self._audio_engine,
            name=current.get("name", ""),
            slots=current.get("slots", []),
            kind=current.get("kind", PlaylistKind.MUSIC),
            folder_path=folder_path,
        )
        if dialog.ShowModal() == wx.ID_OK:
            result = dialog.get_result()
            if result:
                self._playlists[index] = result
                self._refresh_list()
        dialog.Destroy()

    def _on_remove(self, _event: wx.Event) -> None:
        index = self._selected_index()
        if index == wx.NOT_FOUND:
            return
        del self._playlists[index]
        self._refresh_list()

    def _on_accept(self, _event: wx.Event) -> None:
        self._settings.set_playback_fade_seconds(self._fade_ctrl.GetValue())
        self._settings.set_alternate_play_next(self._alternate_checkbox.GetValue())
        self._settings.set_swap_play_select(self._swap_play_select_checkbox.GetValue())
        self._settings.set_auto_remove_played(self._auto_remove_checkbox.GetValue())
        self._settings.set_focus_playing_track(self._focus_playing_checkbox.GetValue())
        self._settings.set_intro_alert_seconds(self._intro_alert_ctrl.GetValue())
        self._settings.set_track_end_alert_seconds(self._track_end_alert_ctrl.GetValue())
        self._settings.set_news_line_length(self._news_line_ctrl.GetValue())
        self._settings.set_startup_playlists(self._playlists)
        self._settings.set_pfl_device(self._selected_pfl_device())
        self._settings.set_language(self._language_codes[self._language_choice.GetSelection()])
        for category_id, checkbox in self._announcement_checkboxes.items():
            self._settings.set_announcement_enabled(category_id, checkbox.GetValue())
        if self._diag_faulthandler_checkbox and self._diag_interval_ctrl:
            self._settings.set_diagnostics_faulthandler(self._diag_faulthandler_checkbox.GetValue())
            self._settings.set_diagnostics_faulthandler_interval(self._diag_interval_ctrl.GetValue())
        if self._diag_loop_checkbox:
            self._settings.set_diagnostics_loop_debug(self._diag_loop_checkbox.GetValue())
        if self._diag_log_level_choice:
            sel = self._diag_log_level_choice.GetSelection()
            if sel != wx.NOT_FOUND:
                levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
                self._settings.set_diagnostics_log_level(levels[sel])
        if (
            self._played_tracks_logging_checkbox
            and self._played_tracks_logging_folder_ctrl
            and self._played_tracks_logging_songs_checkbox
            and self._played_tracks_logging_spots_checkbox
        ):
            self._settings.set_played_tracks_logging_enabled(self._played_tracks_logging_checkbox.GetValue())
            self._settings.set_played_tracks_logging_songs_enabled(self._played_tracks_logging_songs_checkbox.GetValue())
            self._settings.set_played_tracks_logging_spots_enabled(self._played_tracks_logging_spots_checkbox.GetValue())

            output_dir = resolve_output_dir()
            default_folder = output_dir / "logs"
            folder_text = self._played_tracks_logging_folder_ctrl.GetValue().strip()
            folder_value = Path(folder_text).expanduser() if folder_text else default_folder
            if folder_value == default_folder:
                self._settings.set_played_tracks_logging_folder(None)
            else:
                try:
                    rel = folder_value.relative_to(output_dir)
                    self._settings.set_played_tracks_logging_folder(rel)
                except ValueError:
                    self._settings.set_played_tracks_logging_folder(folder_value)

        if (
            self._now_playing_checkbox
            and self._now_playing_path_ctrl
            and self._now_playing_songs_checkbox
            and self._now_playing_spots_checkbox
            and self._now_playing_on_change_checkbox
            and self._now_playing_periodic_checkbox
            and self._now_playing_interval_ctrl
            and self._now_playing_template_ctrl
        ):
            self._settings.set_now_playing_enabled(self._now_playing_checkbox.GetValue())
            self._settings.set_now_playing_songs_enabled(self._now_playing_songs_checkbox.GetValue())
            self._settings.set_now_playing_spots_enabled(self._now_playing_spots_checkbox.GetValue())
            self._settings.set_now_playing_update_on_track_change(self._now_playing_on_change_checkbox.GetValue())
            if self._now_playing_periodic_checkbox.GetValue():
                self._settings.set_now_playing_update_interval_seconds(float(self._now_playing_interval_ctrl.GetValue()))
            else:
                self._settings.set_now_playing_update_interval_seconds(0.0)
            self._settings.set_now_playing_template(self._now_playing_template_ctrl.GetValue())

            output_dir = resolve_output_dir()
            default_path = output_dir / "nowplaying.txt"
            path_text = self._now_playing_path_ctrl.GetValue().strip()
            raw_path = Path(path_text).expanduser() if path_text else default_path
            if raw_path == default_path:
                self._settings.set_now_playing_path(None)
            else:
                try:
                    rel = raw_path.relative_to(output_dir)
                    self._settings.set_now_playing_path(rel)
                except ValueError:
                    self._settings.set_now_playing_path(raw_path)
        self.EndModal(wx.ID_OK)

    def _populate_pfl_choice(self) -> None:
        devices = self._audio_engine.get_devices()
        entries: list[tuple[Optional[str], str]] = [(None, _("(none)"))]
        entries.extend((device.id, device.name) for device in devices)
        self._pfl_entries = entries
        self._pfl_choice.Clear()
        for _device_id, label in entries:
            self._pfl_choice.Append(label)

        current = self._settings.get_pfl_device()
        selection = 0
        if current:
            for index, (device_id, _label) in enumerate(entries):
                if device_id == current:
                    selection = index
                    break
        if entries:
            self._pfl_choice.SetSelection(selection)

    def _selected_pfl_device(self) -> Optional[str]:
        selection = self._pfl_choice.GetSelection()
        if selection == wx.NOT_FOUND or selection >= len(self._pfl_entries):
            return None
        return self._pfl_entries[selection][0]
