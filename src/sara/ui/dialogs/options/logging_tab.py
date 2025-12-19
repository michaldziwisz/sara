"""Logging tab builder for `OptionsDialog`."""

from __future__ import annotations

from pathlib import Path

import wx

from sara.core.env import resolve_output_dir
from sara.core.i18n import gettext as _
from sara.ui.file_selection_dialog import FileSelectionDialog


def _default_log_folder() -> Path:
    return resolve_output_dir() / "logs"


def _default_now_playing_path() -> Path:
    return resolve_output_dir() / "nowplaying.txt"


def build_logging_tab(dialog, notebook: wx.Notebook) -> wx.Panel:
    panel = wx.Panel(notebook)
    sizer = wx.BoxSizer(wx.VERTICAL)

    played_box = wx.StaticBoxSizer(wx.StaticBox(panel, label=_("Played tracks log")), wx.VERTICAL)
    dialog._played_tracks_logging_checkbox = wx.CheckBox(
        panel,
        label=_("Save played tracks to log files"),
    )
    dialog._played_tracks_logging_checkbox.SetName("options_logging_played_enabled")
    dialog._played_tracks_logging_checkbox.SetValue(dialog._settings.get_played_tracks_logging_enabled())
    played_box.Add(dialog._played_tracks_logging_checkbox, 0, wx.ALL, 5)

    folder_row = wx.BoxSizer(wx.HORIZONTAL)
    folder_label = wx.StaticText(panel, label=_("Log folder:"))
    dialog._played_tracks_logging_folder_ctrl = wx.TextCtrl(panel)
    dialog._played_tracks_logging_folder_ctrl.SetName("options_logging_folder")
    configured_folder = dialog._settings.get_played_tracks_logging_folder()
    dialog._played_tracks_logging_folder_ctrl.SetValue(str(configured_folder or _default_log_folder()))
    dialog._played_tracks_logging_folder_button = wx.Button(panel, label=_("Select folder…"))
    dialog._played_tracks_logging_folder_button.SetName("options_logging_folder_browse")
    folder_row.Add(folder_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    folder_row.Add(dialog._played_tracks_logging_folder_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    folder_row.Add(dialog._played_tracks_logging_folder_button, 0, wx.ALIGN_CENTER_VERTICAL)
    played_box.Add(folder_row, 0, wx.EXPAND | wx.ALL, 5)

    types_row = wx.BoxSizer(wx.HORIZONTAL)
    dialog._played_tracks_logging_songs_checkbox = wx.CheckBox(panel, label=_("Save songs"))
    dialog._played_tracks_logging_songs_checkbox.SetName("options_logging_songs")
    dialog._played_tracks_logging_songs_checkbox.SetValue(dialog._settings.get_played_tracks_logging_songs_enabled())
    dialog._played_tracks_logging_spots_checkbox = wx.CheckBox(panel, label=_("Save spots"))
    dialog._played_tracks_logging_spots_checkbox.SetName("options_logging_spots")
    dialog._played_tracks_logging_spots_checkbox.SetValue(dialog._settings.get_played_tracks_logging_spots_enabled())
    types_row.Add(dialog._played_tracks_logging_songs_checkbox, 0, wx.RIGHT, 12)
    types_row.Add(dialog._played_tracks_logging_spots_checkbox, 0)
    played_box.Add(types_row, 0, wx.ALL, 5)

    sizer.Add(played_box, 0, wx.EXPAND | wx.BOTTOM, 10)

    now_box = wx.StaticBoxSizer(wx.StaticBox(panel, label=_("Now playing")), wx.VERTICAL)
    dialog._now_playing_checkbox = wx.CheckBox(
        panel,
        label=_("Save currently playing track to a file"),
    )
    dialog._now_playing_checkbox.SetName("options_nowplaying_enabled")
    dialog._now_playing_checkbox.SetValue(dialog._settings.get_now_playing_enabled())
    now_box.Add(dialog._now_playing_checkbox, 0, wx.ALL, 5)

    path_row = wx.BoxSizer(wx.HORIZONTAL)
    path_label = wx.StaticText(panel, label=_("Now playing file:"))
    dialog._now_playing_path_ctrl = wx.TextCtrl(panel)
    dialog._now_playing_path_ctrl.SetName("options_nowplaying_path")
    configured_path = dialog._settings.get_now_playing_path()
    dialog._now_playing_path_ctrl.SetValue(str(configured_path or _default_now_playing_path()))
    dialog._now_playing_path_button = wx.Button(panel, label=_("Select file…"))
    dialog._now_playing_path_button.SetName("options_nowplaying_path_browse")
    path_row.Add(path_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    path_row.Add(dialog._now_playing_path_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    path_row.Add(dialog._now_playing_path_button, 0, wx.ALIGN_CENTER_VERTICAL)
    now_box.Add(path_row, 0, wx.EXPAND | wx.ALL, 5)

    triggers_box = wx.StaticBoxSizer(wx.StaticBox(panel, label=_("Update triggers")), wx.VERTICAL)
    dialog._now_playing_on_change_checkbox = wx.CheckBox(panel, label=_("On track change"))
    dialog._now_playing_on_change_checkbox.SetName("options_nowplaying_on_change")
    stored_interval = int(dialog._settings.get_now_playing_update_interval_seconds() or 0)
    periodic_enabled = stored_interval > 0
    on_change_enabled = bool(dialog._settings.get_now_playing_update_on_track_change()) and not periodic_enabled
    dialog._now_playing_on_change_checkbox.SetValue(on_change_enabled)
    triggers_box.Add(dialog._now_playing_on_change_checkbox, 0, wx.ALL, 5)

    interval_row = wx.BoxSizer(wx.HORIZONTAL)
    dialog._now_playing_periodic_checkbox = wx.CheckBox(panel, label=_("Update every"))
    dialog._now_playing_periodic_checkbox.SetName("options_nowplaying_periodic")
    interval_ctrl = wx.SpinCtrl(panel, min=1, max=86400)
    interval_ctrl.SetName("options_nowplaying_interval")
    dialog._now_playing_periodic_checkbox.SetValue(periodic_enabled)
    interval_ctrl.SetValue(stored_interval if periodic_enabled else 5)
    dialog._now_playing_interval_ctrl = interval_ctrl
    interval_suffix = wx.StaticText(panel, label=_("seconds"))
    interval_row.Add(dialog._now_playing_periodic_checkbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    interval_row.Add(interval_ctrl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    interval_row.Add(interval_suffix, 0, wx.ALIGN_CENTER_VERTICAL)
    triggers_box.Add(interval_row, 0, wx.ALL, 5)
    now_box.Add(triggers_box, 0, wx.EXPAND | wx.ALL, 5)

    types_row = wx.BoxSizer(wx.HORIZONTAL)
    dialog._now_playing_songs_checkbox = wx.CheckBox(panel, label=_("Include songs"))
    dialog._now_playing_songs_checkbox.SetName("options_nowplaying_songs")
    dialog._now_playing_songs_checkbox.SetValue(dialog._settings.get_now_playing_songs_enabled())
    dialog._now_playing_spots_checkbox = wx.CheckBox(panel, label=_("Include spots"))
    dialog._now_playing_spots_checkbox.SetName("options_nowplaying_spots")
    dialog._now_playing_spots_checkbox.SetValue(dialog._settings.get_now_playing_spots_enabled())
    types_row.Add(dialog._now_playing_songs_checkbox, 0, wx.RIGHT, 12)
    types_row.Add(dialog._now_playing_spots_checkbox, 0)
    now_box.Add(types_row, 0, wx.ALL, 5)

    template_row = wx.BoxSizer(wx.HORIZONTAL)
    template_label = wx.StaticText(panel, label=_("Template:"))
    dialog._now_playing_template_ctrl = wx.TextCtrl(panel)
    dialog._now_playing_template_ctrl.SetName("options_nowplaying_template")
    dialog._now_playing_template_ctrl.SetValue(dialog._settings.get_now_playing_template())
    template_row.Add(template_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    template_row.Add(dialog._now_playing_template_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
    now_box.Add(template_row, 0, wx.EXPAND | wx.ALL, 5)

    sizer.Add(now_box, 0, wx.EXPAND | wx.BOTTOM, 10)

    def _pick_folder(_event: wx.Event) -> None:
        dialog_pick = FileSelectionDialog(
            dialog,
            title=_("Select folder"),
            allow_directories=True,
            directories_only=True,
        )
        try:
            if dialog_pick.ShowModal() != wx.ID_OK:
                return
            paths = dialog_pick.get_paths()
        finally:
            dialog_pick.Destroy()
        if not paths:
            return
        dialog._played_tracks_logging_folder_ctrl.SetValue(paths[0])

    def _pick_file(_event: wx.Event) -> None:
        dialog_pick = FileSelectionDialog(
            dialog,
            title=_("Select file"),
            wildcard=_("Text files (*.txt)|*.txt|All files|*.*"),
            style=wx.FD_SAVE,
        )
        try:
            if dialog_pick.ShowModal() != wx.ID_OK:
                return
            paths = dialog_pick.get_paths()
        finally:
            dialog_pick.Destroy()
        if not paths:
            return
        dialog._now_playing_path_ctrl.SetValue(paths[0])

    def _update_enablement() -> None:
        played_enabled = dialog._played_tracks_logging_checkbox.GetValue()
        for ctrl in (
            dialog._played_tracks_logging_folder_ctrl,
            dialog._played_tracks_logging_folder_button,
            dialog._played_tracks_logging_songs_checkbox,
            dialog._played_tracks_logging_spots_checkbox,
        ):
            ctrl.Enable(played_enabled)

        now_enabled = dialog._now_playing_checkbox.GetValue()
        for ctrl in (
            dialog._now_playing_path_ctrl,
            dialog._now_playing_path_button,
            dialog._now_playing_songs_checkbox,
            dialog._now_playing_spots_checkbox,
            dialog._now_playing_on_change_checkbox,
            dialog._now_playing_periodic_checkbox,
            dialog._now_playing_template_ctrl,
        ):
            ctrl.Enable(now_enabled)
        periodic = bool(dialog._now_playing_periodic_checkbox.GetValue())
        dialog._now_playing_interval_ctrl.Enable(now_enabled and periodic)

    def _on_change_toggle(_evt: wx.Event) -> None:
        if dialog._now_playing_on_change_checkbox.GetValue():
            dialog._now_playing_periodic_checkbox.SetValue(False)
        _update_enablement()

    def _on_periodic_toggle(_evt: wx.Event) -> None:
        if dialog._now_playing_periodic_checkbox.GetValue():
            dialog._now_playing_on_change_checkbox.SetValue(False)
        _update_enablement()

    dialog._played_tracks_logging_folder_button.Bind(wx.EVT_BUTTON, _pick_folder)
    dialog._now_playing_path_button.Bind(wx.EVT_BUTTON, _pick_file)
    dialog._played_tracks_logging_checkbox.Bind(wx.EVT_CHECKBOX, lambda _evt: _update_enablement())
    dialog._now_playing_checkbox.Bind(wx.EVT_CHECKBOX, lambda _evt: _update_enablement())
    dialog._now_playing_on_change_checkbox.Bind(wx.EVT_CHECKBOX, _on_change_toggle)
    dialog._now_playing_periodic_checkbox.Bind(wx.EVT_CHECKBOX, _on_periodic_toggle)

    _update_enablement()
    panel.SetSizer(sizer)
    return panel
