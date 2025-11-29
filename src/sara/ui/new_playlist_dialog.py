"""Dialog for creating a new playlist."""

from __future__ import annotations

from pathlib import Path

import wx

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistKind
from sara.ui.file_selection_dialog import FileSelectionDialog


class NewPlaylistDialog(wx.Dialog):
    """Simple dialog asking for a playlist name."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent, title=_("New playlist"), style=wx.DEFAULT_DIALOG_STYLE)
        self._name_ctrl = wx.TextCtrl(self)
        self._type_choices = (
            (PlaylistKind.MUSIC, _("Music playlist")),
            (PlaylistKind.NEWS, _("News playlist")),
            (PlaylistKind.FOLDER, _("Music folder playlist")),
        )
        type_labels = [choice[1] for choice in self._type_choices]
        self._type_radio = wx.RadioBox(self, label=_("Playlist type:"), choices=type_labels, majorDimension=1, style=wx.RA_SPECIFY_COLS)

        name_label = wx.StaticText(self, label=_("Playlist name:"))
        self._name_ctrl.SetHint(_("e.g. Morning"))

        folder_sizer = wx.BoxSizer(wx.HORIZONTAL)
        folder_label = wx.StaticText(self, label=_("Folder:"))
        self._folder_path_ctrl = wx.TextCtrl(self, style=wx.TE_READONLY)
        self._folder_browse = wx.Button(self, label=_("Select folder…"))
        folder_sizer.Add(folder_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        folder_sizer.Add(self._folder_path_ctrl, 1, wx.RIGHT, 5)
        folder_sizer.Add(self._folder_browse, 0)

        button_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(name_label, 0, wx.ALL, 5)
        main_sizer.Add(self._name_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        main_sizer.Add(self._type_radio, 0, wx.ALL, 5)
        main_sizer.Add(folder_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        main_sizer.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        self.SetSizerAndFit(main_sizer)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self._type_radio.Bind(wx.EVT_RADIOBOX, lambda _evt: self._update_folder_controls())
        self._folder_browse.Bind(wx.EVT_BUTTON, self._browse_folder)
        self._folder_path: Path | None = None
        self._update_folder_controls()
        self._name_ctrl.SetFocus()

    @property
    def playlist_name(self) -> str:
        return self._name_ctrl.GetValue().strip()

    @property
    def playlist_kind(self) -> PlaylistKind:
        selection = self._type_radio.GetSelection()
        return self._type_choices[max(0, selection)][0]

    @property
    def folder_path(self) -> Path | None:
        return self._folder_path

    def _update_folder_controls(self) -> None:
        is_folder = self.playlist_kind is PlaylistKind.FOLDER
        self._folder_path_ctrl.Enable(is_folder)
        self._folder_browse.Enable(is_folder)
        if not is_folder:
            self._folder_path = None
            self._folder_path_ctrl.SetValue("")

    def _browse_folder(self) -> None:
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
            if not paths:
                return
            selected = Path(paths[0])
            if not selected.exists() or not selected.is_dir():
                wx.MessageBox(_("Selected path is not a folder."), _("Error"), parent=self)
                return
            self._folder_path = selected
            self._folder_path_ctrl.SetValue(str(selected))
        finally:
            dialog.Destroy()

    def _on_ok(self, event: wx.CommandEvent) -> None:
        if not self.playlist_name:
            wx.MessageBox(_("Enter a playlist name."), _("Error"), style=wx.ICON_ERROR | wx.OK, parent=self)
            self._name_ctrl.SetFocus()
            return
        if self.playlist_kind is PlaylistKind.FOLDER:
            if not self._folder_path:
                wx.MessageBox(_("Select a folder to populate this playlist."), _("Error"), parent=self)
                return
            if not self._folder_path.exists() or not self._folder_path.is_dir():
                wx.MessageBox(_("Selected folder is not available."), _("Error"), parent=self)
                return
        event.Skip()
