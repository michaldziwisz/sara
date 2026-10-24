"""Ustawienia lokalnego serwera sterowania."""

from __future__ import annotations

import wx

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistKind
from sara.ui.services.accessibility import apply_accessible_label


def build_remote_tab(dialog, notebook: wx.Notebook) -> wx.Panel:
    panel = wx.Panel(notebook)
    sizer = wx.BoxSizer(wx.VERTICAL)
    dialog._remote_enabled_checkbox = wx.CheckBox(
        panel, label=_("Enable local TCP control (127.0.0.1)"),
    )
    dialog._remote_enabled_checkbox.SetValue(dialog._settings.get_remote_enabled())
    apply_accessible_label(dialog._remote_enabled_checkbox, dialog._remote_enabled_checkbox.GetLabel())
    sizer.Add(dialog._remote_enabled_checkbox, 0, wx.ALL, 10)

    row = wx.BoxSizer(wx.HORIZONTAL)
    label = wx.StaticText(panel, label=_("TCP control port:"))
    dialog._remote_port_ctrl = wx.SpinCtrl(panel, min=1, max=65535)
    dialog._remote_port_ctrl.SetValue(dialog._settings.get_remote_port())
    apply_accessible_label(dialog._remote_port_ctrl, label.GetLabel().rstrip(":"))
    row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    row.Add(dialog._remote_port_ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
    sizer.Add(row, 0, wx.ALL, 10)
    row = wx.BoxSizer(wx.HORIZONTAL)
    label = wx.StaticText(panel, label=_("Main music playlist:"))
    frame = dialog.GetParent()
    playlists = getattr(frame, "_playlists", {})
    layout = getattr(frame, "_layout", None)
    order = layout.state.order if layout else []
    entries = [("", _("First music playlist"))]
    entries.extend((pid, playlists[pid].model.name) for pid in order
                   if pid in playlists and playlists[pid].model.kind is PlaylistKind.MUSIC)
    dialog._remote_main_playlist_ids = [pid for pid, name in entries]
    dialog._remote_main_playlist_choice = wx.Choice(panel, choices=[name for pid, name in entries])
    saved = dialog._settings.get_remote_main_playlist()
    selection = dialog._remote_main_playlist_ids.index(saved) if saved in dialog._remote_main_playlist_ids else 0
    dialog._remote_main_playlist_choice.SetSelection(selection)
    apply_accessible_label(dialog._remote_main_playlist_choice, label.GetLabel().rstrip(":"))
    row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    row.Add(dialog._remote_main_playlist_choice, 1, wx.ALIGN_CENTER_VERTICAL)
    sizer.Add(row, 0, wx.EXPAND | wx.ALL, 10)
    info = wx.StaticText(panel, label=_("Only programs on this computer can connect. Changes apply after pressing OK."))
    info.Wrap(460)
    sizer.Add(info, 0, wx.ALL, 10)
    panel.SetSizer(sizer)
    return panel
