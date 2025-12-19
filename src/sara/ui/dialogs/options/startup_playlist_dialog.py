"""Startup playlist dialog extracted from `sara.ui.dialogs.options_dialog`."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import wx

from sara.audio.engine import AudioEngine
from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistKind
from sara.ui.file_selection_dialog import FileSelectionDialog
from sara.ui.playlist_devices_dialog import PlaylistDevicesDialog


class StartupPlaylistDialog(wx.Dialog):
    """Dialog konfiguracji pojedynczej playlisty startowej."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        audio_engine: AudioEngine,
        name: str = "",
        slots: Optional[List[Optional[str]]] = None,
        kind: PlaylistKind = PlaylistKind.MUSIC,
        folder_path: Path | None = None,
    ) -> None:
        super().__init__(parent, title=_("Startup playlist"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._audio_engine = audio_engine
        self._slots: List[Optional[str]] = list(slots or [])
        self._type_choices = (
            (PlaylistKind.MUSIC, _("Music playlist")),
            (PlaylistKind.NEWS, _("News playlist")),
            (PlaylistKind.FOLDER, _("Music folder playlist")),
        )
        self._folder_path: Path | None = folder_path

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        name_label = wx.StaticText(self, label=_("Playlist name:"))
        self._name_ctrl = wx.TextCtrl(self, value=name)
        main_sizer.Add(name_label, 0, wx.ALL, 5)
        main_sizer.Add(self._name_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        type_labels = [choice[1] for choice in self._type_choices]
        self._type_radio = wx.RadioBox(
            self,
            label=_("Playlist type:"),
            choices=type_labels,
            majorDimension=1,
            style=wx.RA_SPECIFY_COLS,
        )
        try:
            selection = next(index for index, choice in enumerate(self._type_choices) if choice[0] == kind)
        except StopIteration:
            selection = 0
        self._type_radio.SetSelection(selection)
        main_sizer.Add(self._type_radio, 0, wx.ALL | wx.EXPAND, 5)

        self._slots_label = wx.StaticText(self, label=self._format_slots())
        main_sizer.Add(self._slots_label, 0, wx.ALL, 5)

        self._folder_row = wx.BoxSizer(wx.HORIZONTAL)
        folder_label = wx.StaticText(self, label=_("Folder:"))
        self._folder_path_ctrl = wx.TextCtrl(self, style=wx.TE_READONLY)
        if folder_path:
            self._folder_path_ctrl.SetValue(str(folder_path))
        self._folder_button = wx.Button(self, label=_("Select folder…"))
        self._folder_row.Add(folder_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self._folder_row.Add(self._folder_path_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self._folder_row.Add(self._folder_button, 0, wx.ALIGN_CENTER_VERTICAL)
        main_sizer.Add(self._folder_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        self._devices_button = wx.Button(self, label=_("Configure players…"))
        self._devices_button.Bind(wx.EVT_BUTTON, self._configure_devices)
        main_sizer.Add(self._devices_button, 0, wx.ALL, 5)

        button_sizer = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if button_sizer:
            main_sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(main_sizer)
        self.Fit()
        self._folder_button.Bind(wx.EVT_BUTTON, self._choose_folder)
        self._type_radio.Bind(wx.EVT_RADIOBOX, lambda _evt: self._update_folder_controls())
        self._update_folder_controls()

    def _configure_devices(self, _event: wx.Event) -> None:
        if self._selected_kind() is PlaylistKind.FOLDER:
            return
        devices = self._audio_engine.get_devices()
        dialog = PlaylistDevicesDialog(self, devices=devices, slots=self._slots)
        if dialog.ShowModal() == wx.ID_OK:
            self._slots = dialog.get_slots()
            self._slots_label.SetLabel(self._format_slots())
        dialog.Destroy()

    def _format_slots(self) -> str:
        if not self._slots:
            return _("No players configured")
        readable = [slot if slot else _("(none)") for slot in self._slots]
        return _("Players: %s") % ", ".join(readable)

    def _selected_kind(self) -> PlaylistKind:
        selection = self._type_radio.GetSelection()
        return self._type_choices[max(0, selection)][0]

    def _choose_folder(self, _event: wx.Event) -> None:
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
            wx.MessageBox(_("Selected folder is not available."), _("Error"), parent=self)
            return
        self._folder_path = selected
        self._folder_path_ctrl.SetValue(str(selected))

    def _update_folder_controls(self) -> None:
        is_folder = self._selected_kind() is PlaylistKind.FOLDER
        self._folder_row.Show(is_folder)
        self._folder_path_ctrl.Enable(is_folder)
        self._folder_button.Enable(is_folder)
        self._devices_button.Enable(not is_folder)
        if is_folder:
            self._slots_label.SetLabel(_("Players: uses PFL device"))
        else:
            self._slots_label.SetLabel(self._format_slots())
        self.Layout()

    def get_result(self) -> Optional[Dict[str, Any]]:
        name = self._name_ctrl.GetValue().strip()
        if not name:
            wx.MessageBox(_("Playlist name cannot be empty."), _("Error"), parent=self)
            return None
        selected_kind = self._selected_kind()
        if selected_kind is PlaylistKind.FOLDER:
            if not self._folder_path:
                wx.MessageBox(_("Select a folder to populate this playlist."), _("Error"), parent=self)
                return None
        result: Dict[str, Any] = {"name": name, "slots": list(self._slots), "kind": selected_kind}
        if selected_kind is PlaylistKind.FOLDER and self._folder_path:
            result["folder_path"] = self._folder_path
        return result

