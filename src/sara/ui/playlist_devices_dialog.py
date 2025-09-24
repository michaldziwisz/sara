"""Dialog for configuring playlist players and devices."""

from __future__ import annotations

from typing import List, Optional

import wx

from sara.audio.engine import AudioDevice
from sara.core.i18n import gettext as _


class PlaylistDevicesDialog(wx.Dialog):
    """Let the user define playlist players and assign audio devices."""

    MAX_SLOTS = 12

    def __init__(
        self,
        parent: wx.Window,
        *,
        devices: List[AudioDevice],
        slots: List[Optional[str]] | None = None,
    ) -> None:
        super().__init__(parent, title=_("Playlist player configuration"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._devices = devices
        self._initial_slots = list(slots or [])
        self._choices: list[wx.Choice] = []

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        info = wx.StaticText(self, label=_("Choose how many players to use and assign audio devices."))
        main_sizer.Add(info, 0, wx.ALL, 10)

        count_sizer = wx.BoxSizer(wx.HORIZONTAL)
        count_label = wx.StaticText(self, label=_("Number of players:"))
        count_sizer.Add(count_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        max_slots = self.MAX_SLOTS
        initial_value = max(len(self._initial_slots), 1)
        if initial_value > max_slots:
            initial_value = max_slots
        self._count_ctrl = wx.SpinCtrl(self, min=1, max=max_slots, initial=initial_value)
        count_sizer.Add(self._count_ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
        main_sizer.Add(count_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self._slots_container = wx.Panel(self)
        self._slots_sizer = wx.FlexGridSizer(rows=0, cols=2, hgap=10, vgap=8)
        self._slots_sizer.AddGrowableCol(1, 1)
        self._slots_container.SetSizer(self._slots_sizer)
        main_sizer.Add(self._slots_container, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        button_sizer = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if button_sizer:
            main_sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 10)

        self.SetSizer(main_sizer)

        self._count_ctrl.Bind(wx.EVT_SPINCTRL, self._on_count_change)
        self._count_ctrl.Bind(wx.EVT_TEXT, self._on_count_change)

        self._rebuild_slot_controls(self._count_ctrl.GetValue())
        self.SetInitialSize((420, 360))

    # region helpers

    def _on_count_change(self, event: wx.Event) -> None:
        try:
            value = int(self._count_ctrl.GetValue())
        except (TypeError, ValueError):
            value = len(self._choices) or 1
        value = max(1, min(value, self.MAX_SLOTS))
        self._count_ctrl.SetValue(value)
        self._rebuild_slot_controls(value)
        event.Skip()

    def _rebuild_slot_controls(self, count: int) -> None:
        if self._choices:
            self._initial_slots = self.get_slots()

        for child in list(self._slots_container.GetChildren()):
            child.Destroy()
        self._choices.clear()

        existing = list(self._initial_slots)
        while len(existing) < count:
            existing.append(None)

        for index in range(count):
            label = wx.StaticText(self._slots_container, label=_("Player %d") % (index + 1))
            choice = wx.Choice(self._slots_container)
            choice.Append(_("(none)"), clientData=None)
            for device in self._devices:
                device_label = f"{device.name} [{device.backend.value.upper()}]"
                if device.is_default:
                    device_label += _(" (default)")
                choice.Append(device_label, clientData=device.id)

            desired = existing[index]
            selection = 0
            if desired is not None:
                for pos in range(choice.GetCount()):
                    if choice.GetClientData(pos) == desired:
                        selection = pos
                        break
            choice.SetSelection(selection)

            self._slots_sizer.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            self._slots_sizer.Add(choice, 1, wx.EXPAND)
            self._choices.append(choice)

        self._initial_slots = existing[:count]
        self._slots_container.Layout()
        self.Layout()

    # endregion

    def get_slots(self) -> list[Optional[str]]:
        slots: list[Optional[str]] = []
        for choice in self._choices:
            selection = choice.GetSelection()
            if selection == wx.NOT_FOUND:
                slots.append(None)
            else:
                slots.append(choice.GetClientData(selection))
        return slots
