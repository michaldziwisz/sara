"""Diagnostics tab builder for `OptionsDialog`."""

from __future__ import annotations

import wx

from sara.core.i18n import gettext as _


def build_diagnostics_tab(dialog, notebook: wx.Notebook) -> wx.Panel:
    diag_panel = wx.Panel(notebook)
    diag_sizer = wx.BoxSizer(wx.VERTICAL)
    diag_box = wx.StaticBoxSizer(wx.StaticBox(diag_panel, label=_("Diagnostics")), wx.VERTICAL)
    dialog._diag_faulthandler_checkbox = wx.CheckBox(
        diag_panel,
        label=_("Periodic stack traces (faulthandler)"),
    )
    dialog._diag_faulthandler_checkbox.SetValue(dialog._settings.get_diagnostics_faulthandler())
    dialog._diag_faulthandler_checkbox.SetName("options_diag_faulthandler")
    diag_box.Add(dialog._diag_faulthandler_checkbox, 0, wx.ALL, 5)

    interval_row = wx.BoxSizer(wx.HORIZONTAL)
    interval_label = wx.StaticText(diag_panel, label=_("Stack trace interval (s, 0 = disable):"))
    dialog._diag_interval_ctrl = wx.SpinCtrlDouble(diag_panel, min=0.0, max=600.0, inc=1.0)
    dialog._diag_interval_ctrl.SetDigits(1)
    dialog._diag_interval_ctrl.SetValue(dialog._settings.get_diagnostics_faulthandler_interval())
    dialog._diag_interval_ctrl.SetName("options_diag_interval_seconds")
    interval_row.Add(interval_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    interval_row.Add(dialog._diag_interval_ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
    diag_box.Add(interval_row, 0, wx.ALL, 5)

    dialog._diag_loop_checkbox = wx.CheckBox(
        diag_panel,
        label=_("Detailed loop debug logging"),
    )
    dialog._diag_loop_checkbox.SetValue(dialog._settings.get_diagnostics_loop_debug())
    dialog._diag_loop_checkbox.SetName("options_diag_loop_debug")
    diag_box.Add(dialog._diag_loop_checkbox, 0, wx.ALL, 5)

    level_row = wx.BoxSizer(wx.HORIZONTAL)
    level_label = wx.StaticText(diag_panel, label=_("Log level:"))
    levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    dialog._diag_log_level_choice = wx.Choice(diag_panel, choices=levels)
    dialog._diag_log_level_choice.SetName("options_diag_log_level")
    try:
        sel = levels.index(dialog._settings.get_diagnostics_log_level())
    except ValueError:
        sel = levels.index("WARNING")
    dialog._diag_log_level_choice.SetSelection(sel)
    level_row.Add(level_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    level_row.Add(dialog._diag_log_level_choice, 0, wx.ALIGN_CENTER_VERTICAL)
    diag_box.Add(level_row, 0, wx.ALL, 5)

    help_text = wx.StaticText(
        diag_panel,
        label=_("Diagnostics options may increase log size and CPU usage. Use only when troubleshooting."),
    )
    help_text.Wrap(440)
    diag_box.Add(help_text, 0, wx.ALL, 5)

    diag_sizer.Add(diag_box, 0, wx.EXPAND | wx.ALL, 10)
    diag_panel.SetSizer(diag_sizer)
    return diag_panel

