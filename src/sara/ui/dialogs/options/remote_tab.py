"""Ustawienia lokalnego serwera sterowania."""

from __future__ import annotations

import wx

from sara.core.i18n import gettext as _
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
    info = wx.StaticText(panel, label=_("Only programs on this computer can connect. Changes apply after pressing OK."))
    info.Wrap(460)
    sizer.Add(info, 0, wx.ALL, 10)
    panel.SetSizer(sizer)
    return panel
