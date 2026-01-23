"""General tab builder for `OptionsDialog`."""

from __future__ import annotations

import wx

from sara.core.i18n import gettext as _
from sara.ui.services.accessibility import apply_accessible_label


def build_general_tab(
    dialog,
    notebook: wx.Notebook,
) -> tuple[wx.Panel, wx.Button, wx.Button, wx.Button]:
    general_panel = wx.Panel(notebook)
    general_sizer = wx.BoxSizer(wx.VERTICAL)

    playback_box = wx.StaticBoxSizer(wx.StaticBox(general_panel, label=_("Playback")), wx.VERTICAL)
    fade_label = wx.StaticText(general_panel, label=_("Default fade out (s):"))
    dialog._fade_ctrl = wx.SpinCtrlDouble(general_panel, min=0.0, max=30.0, inc=0.1)
    dialog._fade_ctrl.SetDigits(2)
    dialog._fade_ctrl.SetValue(dialog._settings.get_playback_fade_seconds())
    apply_accessible_label(dialog._fade_ctrl, fade_label.GetLabel().rstrip(":").strip())
    playback_row = wx.BoxSizer(wx.HORIZONTAL)
    playback_row.Add(fade_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    playback_row.Add(dialog._fade_ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
    playback_box.Add(playback_row, 0, wx.ALL, 5)

    executor_row = wx.BoxSizer(wx.HORIZONTAL)
    executor_label = wx.StaticText(general_panel, label=_("Mix trigger executor:"))
    dialog._mix_executor_codes = ["ui", "thread"]
    executor_names = [_("UI (wx)"), _("Thread (low latency)")]
    dialog._mix_executor_choice = wx.Choice(general_panel, choices=executor_names)
    apply_accessible_label(dialog._mix_executor_choice, executor_label.GetLabel().rstrip(":").strip())
    current_executor = dialog._settings.get_playback_mix_executor()
    try:
        executor_selection = dialog._mix_executor_codes.index(current_executor)
    except ValueError:
        executor_selection = 0
    dialog._mix_executor_choice.SetSelection(executor_selection)
    executor_row.Add(executor_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    executor_row.Add(dialog._mix_executor_choice, 0, wx.ALIGN_CENTER_VERTICAL)
    playback_box.Add(executor_row, 0, wx.ALL, 5)

    dialog._alternate_checkbox = wx.CheckBox(
        general_panel,
        label=_("Alternate playlists with Space key"),
    )
    dialog._alternate_checkbox.SetValue(dialog._settings.get_alternate_play_next())
    apply_accessible_label(dialog._alternate_checkbox, dialog._alternate_checkbox.GetLabel())
    playback_box.Add(dialog._alternate_checkbox, 0, wx.ALL, 5)

    dialog._swap_play_select_checkbox = wx.CheckBox(
        general_panel,
        label=_("Swap play/select on music playlists (Space selects, Enter plays)"),
    )
    dialog._swap_play_select_checkbox.SetValue(dialog._settings.get_swap_play_select())
    apply_accessible_label(dialog._swap_play_select_checkbox, dialog._swap_play_select_checkbox.GetLabel())
    playback_box.Add(dialog._swap_play_select_checkbox, 0, wx.ALL, 5)

    dialog._auto_remove_checkbox = wx.CheckBox(
        general_panel,
        label=_("Automatically remove played tracks"),
    )
    dialog._auto_remove_checkbox.SetValue(dialog._settings.get_auto_remove_played())
    apply_accessible_label(dialog._auto_remove_checkbox, dialog._auto_remove_checkbox.GetLabel())
    playback_box.Add(dialog._auto_remove_checkbox, 0, wx.ALL, 5)

    intro_row = wx.BoxSizer(wx.HORIZONTAL)
    intro_label = wx.StaticText(general_panel, label=_("Intro alert (s):"))
    dialog._intro_alert_ctrl = wx.SpinCtrlDouble(general_panel, min=0.0, max=60.0, inc=0.5)
    dialog._intro_alert_ctrl.SetDigits(1)
    dialog._intro_alert_ctrl.SetValue(dialog._settings.get_intro_alert_seconds())
    apply_accessible_label(dialog._intro_alert_ctrl, intro_label.GetLabel().rstrip(":").strip())
    intro_row.Add(intro_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    intro_row.Add(dialog._intro_alert_ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
    playback_box.Add(intro_row, 0, wx.ALL, 5)

    end_row = wx.BoxSizer(wx.HORIZONTAL)
    end_label = wx.StaticText(general_panel, label=_("Track end alert (s):"))
    dialog._track_end_alert_ctrl = wx.SpinCtrlDouble(general_panel, min=0.0, max=120.0, inc=0.5)
    dialog._track_end_alert_ctrl.SetDigits(1)
    dialog._track_end_alert_ctrl.SetValue(dialog._settings.get_track_end_alert_seconds())
    apply_accessible_label(dialog._track_end_alert_ctrl, end_label.GetLabel().rstrip(":").strip())
    end_row.Add(end_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    end_row.Add(dialog._track_end_alert_ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
    playback_box.Add(end_row, 0, wx.ALL, 5)

    language_row = wx.BoxSizer(wx.HORIZONTAL)
    language_label = wx.StaticText(general_panel, label=_("Interface language:"))
    dialog._language_codes = ["en", "pl"]
    language_names = [_("English"), _("Polish")]
    dialog._language_choice = wx.Choice(general_panel, choices=language_names)
    current_language = dialog._settings.get_language()
    apply_accessible_label(dialog._language_choice, language_label.GetLabel().rstrip(":").strip())
    try:
        selection = dialog._language_codes.index(current_language)
    except ValueError:
        selection = 0
    dialog._language_choice.SetSelection(selection)
    language_row.Add(language_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    language_row.Add(dialog._language_choice, 0, wx.ALIGN_CENTER_VERTICAL)
    playback_box.Add(language_row, 0, wx.ALL, 5)
    general_sizer.Add(playback_box, 0, wx.EXPAND | wx.BOTTOM, 10)

    pfl_box = wx.StaticBoxSizer(wx.StaticBox(general_panel, label=_("Pre-fader listen (PFL)")), wx.VERTICAL)
    pfl_row = wx.BoxSizer(wx.HORIZONTAL)
    pfl_label = wx.StaticText(general_panel, label=_("PFL device:"))
    dialog._pfl_choice = wx.Choice(general_panel)
    apply_accessible_label(dialog._pfl_choice, pfl_label.GetLabel().rstrip(":").strip())
    pfl_row.Add(pfl_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    pfl_row.Add(dialog._pfl_choice, 1, wx.ALIGN_CENTER_VERTICAL)
    pfl_box.Add(pfl_row, 0, wx.EXPAND | wx.ALL, 5)
    general_sizer.Add(pfl_box, 0, wx.EXPAND | wx.BOTTOM, 10)

    startup_box = wx.StaticBoxSizer(wx.StaticBox(general_panel, label=_("Startup playlists")), wx.VERTICAL)
    dialog._playlists_list = wx.ListCtrl(general_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
    apply_accessible_label(dialog._playlists_list, startup_box.GetStaticBox().GetLabel())
    dialog._playlists_list.InsertColumn(0, _("Name"))
    dialog._playlists_list.InsertColumn(1, _("Type"))
    dialog._playlists_list.InsertColumn(2, _("Players"))
    startup_box.Add(dialog._playlists_list, 1, wx.EXPAND | wx.ALL, 5)

    buttons_row = wx.BoxSizer(wx.HORIZONTAL)
    add_btn = wx.Button(general_panel, label=_("Add…"))
    edit_btn = wx.Button(general_panel, label=_("Edit…"))
    remove_btn = wx.Button(general_panel, label=_("Remove"))
    apply_accessible_label(add_btn, add_btn.GetLabel())
    apply_accessible_label(edit_btn, edit_btn.GetLabel())
    apply_accessible_label(remove_btn, remove_btn.GetLabel())
    buttons_row.Add(add_btn, 0, wx.RIGHT, 5)
    buttons_row.Add(edit_btn, 0, wx.RIGHT, 5)
    buttons_row.Add(remove_btn, 0)
    startup_box.Add(buttons_row, 0, wx.ALL | wx.ALIGN_RIGHT, 5)
    general_sizer.Add(startup_box, 1, wx.EXPAND | wx.BOTTOM, 10)

    news_box = wx.StaticBoxSizer(wx.StaticBox(general_panel, label=_("News playlists")), wx.VERTICAL)
    news_row = wx.BoxSizer(wx.HORIZONTAL)
    news_label = wx.StaticText(
        general_panel,
        label=_("Read-mode line length (characters, 0 = unlimited):"),
    )
    dialog._news_line_ctrl = wx.SpinCtrl(general_panel, min=0, max=400)
    apply_accessible_label(dialog._news_line_ctrl, news_label.GetLabel().rstrip(":").strip())
    dialog._news_line_ctrl.SetValue(dialog._settings.get_news_line_length())
    news_row.Add(news_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    news_row.Add(dialog._news_line_ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
    news_box.Add(news_row, 0, wx.ALL, 5)
    general_sizer.Add(news_box, 0, wx.EXPAND | wx.BOTTOM, 10)

    general_panel.SetSizer(general_sizer)
    return general_panel, add_btn, edit_btn, remove_btn
