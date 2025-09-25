"""Okno dialogowe z ustawieniami globalnymi aplikacji."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import wx

from sara.audio.engine import AudioDevice, AudioEngine
from sara.core.config import SettingsManager
from sara.core.announcement_registry import ANNOUNCEMENT_CATEGORIES
from sara.core.i18n import gettext as _
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
    ) -> None:
        super().__init__(parent, title=_("Startup playlist"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._audio_engine = audio_engine
        self._slots: List[Optional[str]] = list(slots or [])

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        name_label = wx.StaticText(self, label=_("Playlist name:"))
        self._name_ctrl = wx.TextCtrl(self, value=name)
        main_sizer.Add(name_label, 0, wx.ALL, 5)
        main_sizer.Add(self._name_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

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
        return {"name": name, "slots": list(self._slots)}


class OptionsDialog(wx.Dialog):
    """Main application settings window."""

    def __init__(self, parent: wx.Window, *, settings: SettingsManager, audio_engine: AudioEngine) -> None:
        super().__init__(parent, title=_("Options"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._settings = settings
        self._audio_engine = audio_engine

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        self._pfl_entries: list[tuple[Optional[str], str]] = []
        self._announcement_checkboxes: dict[str, wx.CheckBox] = {}

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

        self._auto_remove_checkbox = wx.CheckBox(
            general_panel,
            label=_("Automatically remove played tracks"),
        )
        self._auto_remove_checkbox.SetValue(self._settings.get_auto_remove_played())
        playback_box.Add(self._auto_remove_checkbox, 0, wx.ALL, 5)

        self._focus_playing_checkbox = wx.CheckBox(
            general_panel,
            label=_("Keep selection on currently playing track"),
        )
        self._focus_playing_checkbox.SetValue(self._settings.get_focus_playing_track())
        playback_box.Add(self._focus_playing_checkbox, 0, wx.ALL, 5)

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
        self._playlists_list.InsertColumn(1, _("Players"))
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

        accessibility_sizer.Add(accessibility_box, 0, wx.EXPAND | wx.ALL, 10)
        accessibility_panel.SetSizer(accessibility_sizer)
        notebook.AddPage(accessibility_panel, _("Accessibility"))

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
            index = self._playlists_list.InsertItem(self._playlists_list.GetItemCount(), entry["name"])
            slot_count = sum(1 for slot in entry.get("slots", []) if slot)
            self._playlists_list.SetItem(index, 1, str(slot_count))
        self._playlists_list.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        self._playlists_list.SetColumnWidth(1, wx.LIST_AUTOSIZE_USEHEADER)

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
        self._settings.set_auto_remove_played(self._auto_remove_checkbox.GetValue())
        self._settings.set_focus_playing_track(self._focus_playing_checkbox.GetValue())
        self._settings.set_intro_alert_seconds(self._intro_alert_ctrl.GetValue())
        self._settings.set_startup_playlists(self._playlists)
        self._settings.set_pfl_device(self._selected_pfl_device())
        self._settings.set_language(self._language_codes[self._language_choice.GetSelection()])
        for category_id, checkbox in self._announcement_checkboxes.items():
            self._settings.set_announcement_enabled(category_id, checkbox.GetValue())
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
