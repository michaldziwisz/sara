"""Dialog for creating a new playlist."""

from __future__ import annotations

import wx

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistKind


class NewPlaylistDialog(wx.Dialog):
    """Simple dialog asking for a playlist name."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent, title=_("New playlist"), style=wx.DEFAULT_DIALOG_STYLE)
        self._name_ctrl = wx.TextCtrl(self)
        self._type_choices = (
            (PlaylistKind.MUSIC, _("Music playlist")),
            (PlaylistKind.NEWS, _("News playlist")),
        )
        type_labels = [choice[1] for choice in self._type_choices]
        self._type_radio = wx.RadioBox(self, label=_("Playlist type:"), choices=type_labels, majorDimension=1, style=wx.RA_SPECIFY_COLS)

        name_label = wx.StaticText(self, label=_("Playlist name:"))
        self._name_ctrl.SetHint(_("e.g. Morning"))

        button_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(name_label, 0, wx.ALL, 5)
        main_sizer.Add(self._name_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        main_sizer.Add(self._type_radio, 0, wx.ALL, 5)
        main_sizer.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        self.SetSizerAndFit(main_sizer)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

    @property
    def playlist_name(self) -> str:
        return self._name_ctrl.GetValue().strip()

    @property
    def playlist_kind(self) -> PlaylistKind:
        selection = self._type_radio.GetSelection()
        return self._type_choices[max(0, selection)][0]

    def _on_ok(self, event: wx.CommandEvent) -> None:
        if not self.playlist_name:
            wx.MessageBox(_("Enter a playlist name."), _("Error"), style=wx.ICON_ERROR | wx.OK, parent=self)
            self._name_ctrl.SetFocus()
            return
        event.Skip()
