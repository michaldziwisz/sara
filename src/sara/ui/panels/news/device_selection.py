"""Device selection helpers for `NewsPlaylistPanel`."""

from __future__ import annotations

import wx


def populate_devices(panel) -> None:
    devices = list(panel._get_audio_devices())
    selection = 0
    panel._device_choice.Clear()
    for idx, (device_id, label) in enumerate(devices):
        panel._device_choice.Append(label, clientData=device_id)
        current = panel.model.output_device or (panel.model.output_slots[0] if panel.model.output_slots else None)
        if device_id == current:
            selection = idx
    if devices:
        panel._device_choice.SetSelection(selection)
        panel._device_choice.Enable(True)
    else:
        panel._device_choice.Enable(False)


def on_device_selected(panel, event: wx.CommandEvent) -> None:
    index = event.GetSelection()
    if index == wx.NOT_FOUND:
        return
    device_id = panel._device_choice.GetClientData(index)
    device_value = str(device_id) if device_id else None
    panel.model.output_device = device_value
    if device_value:
        panel.model.set_output_slots([device_value])
    else:
        panel.model.set_output_slots([])
    panel._on_device_change(panel.model)


def get_selected_device_id(panel) -> str | None:
    selection = panel._device_choice.GetSelection()
    if selection == wx.NOT_FOUND:
        return None
    data = panel._device_choice.GetClientData(selection)
    return str(data) if data else None

