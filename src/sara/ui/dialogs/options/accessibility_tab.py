"""Accessibility tab builder for `OptionsDialog`."""

from __future__ import annotations

import wx

from sara.core.announcement_registry import ANNOUNCEMENT_CATEGORIES
from sara.core.i18n import gettext as _


def build_accessibility_tab(dialog, notebook: wx.Notebook) -> wx.Panel:
    accessibility_panel = wx.Panel(notebook)
    accessibility_sizer = wx.BoxSizer(wx.VERTICAL)

    accessibility_box = wx.StaticBoxSizer(
        wx.StaticBox(accessibility_panel, label=_("Announcements")),
        wx.VERTICAL,
    )
    announcements = dialog._settings.get_all_announcement_settings()
    info_label = wx.StaticText(
        accessibility_panel,
        label=_("Choose which announcements should be spoken by the screen reader."),
    )
    info_label.Wrap(440)
    accessibility_box.Add(info_label, 0, wx.ALL, 5)

    for category in ANNOUNCEMENT_CATEGORIES:
        checkbox = wx.CheckBox(accessibility_panel, label=_(category.label))
        checkbox.SetValue(announcements.get(category.id, category.default_enabled))
        checkbox.SetName(f"options_announce_{category.id}")
        accessibility_box.Add(checkbox, 0, wx.ALL, 4)
        dialog._announcement_checkboxes[category.id] = checkbox

    dialog._focus_playing_checkbox = wx.CheckBox(
        accessibility_panel,
        label=_("Keep selection on currently playing track"),
    )
    dialog._focus_playing_checkbox.SetValue(dialog._settings.get_focus_playing_track())
    dialog._focus_playing_checkbox.SetName("options_focus_playing_selection")
    accessibility_box.Add(dialog._focus_playing_checkbox, 0, wx.ALL, 4)

    accessibility_sizer.Add(accessibility_box, 0, wx.EXPAND | wx.ALL, 10)
    accessibility_panel.SetSizer(accessibility_sizer)
    return accessibility_panel

