"""Okno dialogowe z ustawieniami globalnymi aplikacji."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import wx

from sara.audio.engine import AudioDevice, AudioEngine
from sara.core.config import SettingsManager
from sara.core.announcement_registry import ANNOUNCEMENT_CATEGORIES
from sara.core.i18n import gettext as _
from sara.ui.playlist_devices_dialog import PlaylistDevicesDialog
from sara.core.playlist import PlaylistKind


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
    ) -> None:
        super().__init__(parent, title=_("Startup playlist"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._audio_engine = audio_engine
        self._slots: List[Optional[str]] = list(slots or [])
        self._type_choices = (
            (PlaylistKind.MUSIC, _("Music playlist")),
            (PlaylistKind.NEWS, _("News playlist")),
        )

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        name_label = wx.StaticText(self, label=_("Playlist name:"))
        self._name_ctrl = wx.TextCtrl(self, value=name)
        main_sizer.Add(name_label, 0, wx.ALL, 5)
        main_sizer.Add(self._name_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        type_labels = [choice[1] for choice in self._type_choices]
        self._type_radio = wx.RadioBox(self, label=_("Playlist type:"), choices=type_labels, majorDimension=1, style=wx.RA_SPECIFY_COLS)
        try:
            selection = next(index for index, choice in enumerate(self._type_choices) if choice[0] == kind)
        except StopIteration:
            selection = 0
        self._type_radio.SetSelection(selection)
        main_sizer.Add(self._type_radio, 0, wx.ALL | wx.EXPAND, 5)

        self._slots_label = wx.StaticText(self, label=self._format_slots())
        main_sizer.Add(self._slots_label, 0, wx.ALL, 5)

        devices_button = wx.Button(self, label=_("Configure players…"))
        devices_button.Bind(wx.EVT_BUTTON, self._configure_devices)
        main_sizer.Add(devices_button, 0, wx.ALL, 5)

        button_sizer = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if button_sizer:
            main_sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(main_sizer)
        self.Fit()

    def _configure_devices(self, _event: wx.Event) -> None:
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

    def get_result(self) -> Optional[Dict[str, Any]]:
        name = self._name_ctrl.GetValue().strip()
        if not name:
            wx.MessageBox(_("Playlist name cannot be empty."), _("Error"), parent=self)
            return None
        selection = self._type_radio.GetSelection()
        selected_kind = self._type_choices[max(0, selection)][0]
        return {"name": name, "slots": list(self._slots), "kind": selected_kind}


class OptionsDialog(wx.Dialog):
    """Main application settings window."""

    def __init__(self, parent: wx.Window, *, settings: SettingsManager, audio_engine: AudioEngine) -> None:
        super().__init__(parent, title=_("Options"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._settings = settings
        self._audio_engine = audio_engine

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        self._pfl_entries: list[tuple[Optional[str], str]] = []
        self._announcement_checkboxes: dict[str, wx.CheckBox] = {}
        self._diag_faulthandler_checkbox: Optional[wx.CheckBox] = None
        self._diag_interval_ctrl: Optional[wx.SpinCtrlDouble] = None
        self._diag_loop_checkbox: Optional[wx.CheckBox] = None
        self._diag_log_level_choice: Optional[wx.Choice] = None

        notebook = wx.Notebook(self)
        main_sizer.Add(notebook, 1, wx.EXPAND | wx.ALL, 10)

        general_panel = wx.Panel(notebook)
        general_sizer = wx.BoxSizer(wx.VERTICAL)

        playback_box = wx.StaticBoxSizer(wx.StaticBox(general_panel, label=_("Playback")), wx.VERTICAL)
        fade_label = wx.StaticText(general_panel, label=_("Default fade out (s):"))
        self._fade_ctrl = wx.SpinCtrlDouble(general_panel, min=0.0, max=30.0, inc=0.1)
        self._fade_ctrl.SetDigits(2)
        self._fade_ctrl.SetValue(self._settings.get_playback_fade_seconds())
        playback_row = wx.BoxSizer(wx.HORIZONTAL)
        playback_row.Add(fade_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        playback_row.Add(self._fade_ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
        playback_box.Add(playback_row, 0, wx.ALL, 5)

        self._alternate_checkbox = wx.CheckBox(
            general_panel,
            label=_("Alternate playlists with Space key"),
        )
        self._alternate_checkbox.SetValue(self._settings.get_alternate_play_next())
        playback_box.Add(self._alternate_checkbox, 0, wx.ALL, 5)

        self._swap_play_select_checkbox = wx.CheckBox(
            general_panel,
            label=_("Swap play/select on music playlists (Space selects, Enter plays)"),
        )
        self._swap_play_select_checkbox.SetValue(self._settings.get_swap_play_select())
        playback_box.Add(self._swap_play_select_checkbox, 0, wx.ALL, 5)

        self._auto_remove_checkbox = wx.CheckBox(
            general_panel,
            label=_("Automatically remove played tracks"),
        )
        self._auto_remove_checkbox.SetValue(self._settings.get_auto_remove_played())
        playback_box.Add(self._auto_remove_checkbox, 0, wx.ALL, 5)

        intro_row = wx.BoxSizer(wx.HORIZONTAL)
        intro_label = wx.StaticText(general_panel, label=_("Intro alert (s):"))
        self._intro_alert_ctrl = wx.SpinCtrlDouble(general_panel, min=0.0, max=60.0, inc=0.5)
        self._intro_alert_ctrl.SetDigits(1)
        self._intro_alert_ctrl.SetValue(self._settings.get_intro_alert_seconds())
        intro_row.Add(intro_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        intro_row.Add(self._intro_alert_ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
        playback_box.Add(intro_row, 0, wx.ALL, 5)

        language_row = wx.BoxSizer(wx.HORIZONTAL)
        language_label = wx.StaticText(general_panel, label=_("Interface language:"))
        self._language_codes = ["en", "pl"]
        language_names = [_("English"), _("Polish")]
        self._language_choice = wx.Choice(general_panel, choices=language_names)
        current_language = self._settings.get_language()
        try:
            selection = self._language_codes.index(current_language)
        except ValueError:
            selection = 0
        self._language_choice.SetSelection(selection)
        language_row.Add(language_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        language_row.Add(self._language_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        playback_box.Add(language_row, 0, wx.ALL, 5)
        general_sizer.Add(playback_box, 0, wx.EXPAND | wx.BOTTOM, 10)

        pfl_box = wx.StaticBoxSizer(wx.StaticBox(general_panel, label=_("Pre-fader listen (PFL)")), wx.VERTICAL)
        pfl_row = wx.BoxSizer(wx.HORIZONTAL)
        pfl_label = wx.StaticText(general_panel, label=_("PFL device:"))
        self._pfl_choice = wx.Choice(general_panel)
        pfl_row.Add(pfl_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        pfl_row.Add(self._pfl_choice, 1, wx.ALIGN_CENTER_VERTICAL)
        pfl_box.Add(pfl_row, 0, wx.EXPAND | wx.ALL, 5)
        general_sizer.Add(pfl_box, 0, wx.EXPAND | wx.BOTTOM, 10)

        startup_box = wx.StaticBoxSizer(wx.StaticBox(general_panel, label=_("Startup playlists")), wx.VERTICAL)
        self._playlists_list = wx.ListCtrl(general_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._playlists_list.InsertColumn(0, _("Name"))
        self._playlists_list.InsertColumn(1, _("Type"))
        self._playlists_list.InsertColumn(2, _("Players"))
        startup_box.Add(self._playlists_list, 1, wx.EXPAND | wx.ALL, 5)

        buttons_row = wx.BoxSizer(wx.HORIZONTAL)
        add_btn = wx.Button(general_panel, label=_("Add…"))
        edit_btn = wx.Button(general_panel, label=_("Edit…"))
        remove_btn = wx.Button(general_panel, label=_("Remove"))
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
        self._news_line_ctrl = wx.SpinCtrl(general_panel, min=0, max=400)
        self._news_line_ctrl.SetValue(self._settings.get_news_line_length())
        news_row.Add(news_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        news_row.Add(self._news_line_ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
        news_box.Add(news_row, 0, wx.ALL, 5)
        general_sizer.Add(news_box, 0, wx.EXPAND | wx.BOTTOM, 10)

        general_panel.SetSizer(general_sizer)
        notebook.AddPage(general_panel, _("General"))

        accessibility_panel = wx.Panel(notebook)
        accessibility_sizer = wx.BoxSizer(wx.VERTICAL)

        accessibility_box = wx.StaticBoxSizer(wx.StaticBox(accessibility_panel, label=_("Announcements")), wx.VERTICAL)
        announcements = self._settings.get_all_announcement_settings()
        info_label = wx.StaticText(
            accessibility_panel,
            label=_("Choose which announcements should be spoken by the screen reader."),
        )
        info_label.Wrap(440)
        accessibility_box.Add(info_label, 0, wx.ALL, 5)

        for category in ANNOUNCEMENT_CATEGORIES:
            checkbox = wx.CheckBox(accessibility_panel, label=_(category.label))
            checkbox.SetValue(announcements.get(category.id, category.default_enabled))
            accessibility_box.Add(checkbox, 0, wx.ALL, 4)
            self._announcement_checkboxes[category.id] = checkbox

        self._focus_playing_checkbox = wx.CheckBox(
            accessibility_panel,
            label=_("Keep selection on currently playing track"),
        )
        self._focus_playing_checkbox.SetValue(self._settings.get_focus_playing_track())
        accessibility_box.Add(self._focus_playing_checkbox, 0, wx.ALL, 4)

        accessibility_sizer.Add(accessibility_box, 0, wx.EXPAND | wx.ALL, 10)
        accessibility_panel.SetSizer(accessibility_sizer)
        notebook.AddPage(accessibility_panel, _("Accessibility"))

        diag_panel = wx.Panel(notebook)
        diag_sizer = wx.BoxSizer(wx.VERTICAL)
        diag_box = wx.StaticBoxSizer(wx.StaticBox(diag_panel, label=_("Diagnostics")), wx.VERTICAL)
        self._diag_faulthandler_checkbox = wx.CheckBox(
            diag_panel,
            label=_("Periodic stack traces (faulthandler)"),
        )
        self._diag_faulthandler_checkbox.SetValue(self._settings.get_diagnostics_faulthandler())
        diag_box.Add(self._diag_faulthandler_checkbox, 0, wx.ALL, 5)

        interval_row = wx.BoxSizer(wx.HORIZONTAL)
        interval_label = wx.StaticText(diag_panel, label=_("Stack trace interval (s, 0 = disable):"))
        self._diag_interval_ctrl = wx.SpinCtrlDouble(diag_panel, min=0.0, max=600.0, inc=1.0)
        self._diag_interval_ctrl.SetDigits(1)
        self._diag_interval_ctrl.SetValue(self._settings.get_diagnostics_faulthandler_interval())
        interval_row.Add(interval_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        interval_row.Add(self._diag_interval_ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
        diag_box.Add(interval_row, 0, wx.ALL, 5)

        self._diag_loop_checkbox = wx.CheckBox(
            diag_panel,
            label=_("Detailed loop debug logging"),
        )
        self._diag_loop_checkbox.SetValue(self._settings.get_diagnostics_loop_debug())
        diag_box.Add(self._diag_loop_checkbox, 0, wx.ALL, 5)

        level_row = wx.BoxSizer(wx.HORIZONTAL)
        level_label = wx.StaticText(diag_panel, label=_("Log level:"))
        levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        self._diag_log_level_choice = wx.Choice(diag_panel, choices=levels)
        try:
            sel = levels.index(self._settings.get_diagnostics_log_level())
        except ValueError:
            sel = levels.index("WARNING")
        self._diag_log_level_choice.SetSelection(sel)
        level_row.Add(level_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        level_row.Add(self._diag_log_level_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        diag_box.Add(level_row, 0, wx.ALL, 5)

        help_text = wx.StaticText(
            diag_panel,
            label=_("Diagnostics options may increase log size and CPU usage. Use only when troubleshooting."),
        )
        help_text.Wrap(440)
        diag_box.Add(help_text, 0, wx.ALL, 5)

        diag_sizer.Add(diag_box, 0, wx.EXPAND | wx.ALL, 10)
        diag_panel.SetSizer(diag_sizer)
        notebook.AddPage(diag_panel, _("Diagnostics"))

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
            kind_label = _("Music") if kind is PlaylistKind.MUSIC else _("News")
            self._playlists_list.SetItem(index, 1, kind_label)
            slot_count = sum(1 for slot in entry.get("slots", []) if slot)
            self._playlists_list.SetItem(index, 2, str(slot_count))
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
        dialog = StartupPlaylistDialog(
            self,
            audio_engine=self._audio_engine,
            name=current.get("name", ""),
            slots=current.get("slots", []),
            kind=current.get("kind", PlaylistKind.MUSIC),
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
