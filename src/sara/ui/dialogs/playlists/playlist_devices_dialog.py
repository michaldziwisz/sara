"""Dialog for configuring playlist players and audio devices."""

from __future__ import annotations

from typing import List, Optional, Dict, DefaultDict
from collections import defaultdict

import wx

from sara.audio.engine import AudioDevice, BackendType
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
        self._backend_choices: list[wx.Choice] = []
        self._device_choices: list[wx.Choice] = []
        self._devices_by_backend: Dict[BackendType, List[AudioDevice]] = defaultdict(list)
        for dev in devices:
            self._devices_by_backend[dev.backend].append(dev)

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
        self._slots_sizer = wx.FlexGridSizer(rows=0, cols=3, hgap=10, vgap=8)
        self._slots_sizer.AddGrowableCol(2, 1)
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
            value = len(self._device_choices) or 1
        value = max(1, min(value, self.MAX_SLOTS))
        self._count_ctrl.SetValue(value)
        self._rebuild_slot_controls(value)
        event.Skip()

    def _rebuild_slot_controls(self, count: int) -> None:
        if self._device_choices:
            self._initial_slots = self.get_slots()

        for child in list(self._slots_container.GetChildren()):
            child.Destroy()
        self._backend_choices.clear()
        self._device_choices.clear()

        existing = list(self._initial_slots)
        while len(existing) < count:
            existing.append(None)

        for index in range(count):
            label = wx.StaticText(self._slots_container, label=_("Player %d") % (index + 1))
            backend_choice = wx.Choice(self._slots_container)
            device_choice = wx.Choice(self._slots_container)

            # backend options
            backends = sorted(self._devices_by_backend.keys(), key=lambda b: b.value)
            for backend in backends:
                backend_choice.Append(backend.value.upper(), clientData=backend)

            # preselect backend based on existing device id
            desired_id = existing[index]
            desired_backend = None
            if desired_id:
                for dev in self._devices:
                    if dev.id == desired_id:
                        desired_backend = dev.backend
                        break
            if desired_backend is None and backends:
                desired_backend = backends[0]

            sel_backend_idx = 0
            if desired_backend is not None:
                for pos in range(backend_choice.GetCount()):
                    if backend_choice.GetClientData(pos) == desired_backend:
                        sel_backend_idx = pos
                        break
            backend_choice.SetSelection(sel_backend_idx)

            self._slots_sizer.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            self._slots_sizer.Add(backend_choice, 0, wx.ALIGN_CENTER_VERTICAL)
            self._slots_sizer.Add(device_choice, 1, wx.EXPAND)
            self._backend_choices.append(backend_choice)
            self._device_choices.append(device_choice)

            def refresh_devices_for(idx: int) -> None:
                backend = self._backend_choices[idx].GetClientData(self._backend_choices[idx].GetSelection())
                device_choice = self._device_choices[idx]
                device_choice.Clear()
                device_choice.Append(_("(none)"), clientData=None)
                for dev in self._devices_by_backend.get(backend, []):
                    label = dev.name
                    if dev.is_default:
                        label += _(" (default)")
                    device_choice.Append(label, clientData=dev.id)
                # reselect previous if still matches backend
                prev = existing[idx]
                sel = 0
                if prev:
                    for pos in range(device_choice.GetCount()):
                        if device_choice.GetClientData(pos) == prev:
                            sel = pos
                            break
                device_choice.SetSelection(sel)

            backend_choice.Bind(wx.EVT_CHOICE, lambda evt, i=index: refresh_devices_for(i))
            refresh_devices_for(index)

        self._initial_slots = existing[:count]
        self._slots_container.Layout()
        self.Layout()

    # endregion

    def get_slots(self) -> list[Optional[str]]:
        slots: list[Optional[str]] = []
        for device_choice in self._device_choices:
            selection = device_choice.GetSelection()
            if selection == wx.NOT_FOUND:
                slots.append(None)
            else:
                slots.append(device_choice.GetClientData(selection))
        return slots
