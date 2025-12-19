"""Toolbar focus/navigation helpers for `NewsPlaylistPanel`."""

from __future__ import annotations

import wx


def toolbar_focusables(panel) -> list[wx.Window]:
    controls: list[wx.Window] = [
        panel._mode_button,
        panel._insert_button,
        panel._load_button,
        panel._save_button,
    ]
    if panel._line_length_spin:
        controls.append(panel._line_length_spin)
    if panel._line_length_apply:
        controls.append(panel._line_length_apply)
    controls.append(panel._device_choice)
    return [ctrl for ctrl in controls if ctrl and ctrl.IsShown() and ctrl.IsEnabled()]


def focus_toolbar_from_text(panel, *, backwards: bool) -> bool:
    controls = toolbar_focusables(panel)
    if not controls:
        return False
    panel._update_caret_from_read()
    target = controls[-1] if backwards else controls[0]
    target.SetFocus()
    return True


def move_within_toolbar(panel, current: wx.Window, *, backwards: bool) -> bool:
    controls = toolbar_focusables(panel)
    if not controls:
        return False
    try:
        index = controls.index(current)
    except ValueError:
        return False
    if backwards:
        if index > 0:
            controls[index - 1].SetFocus()
            return True
        if focus_content_area(panel):
            return True
        panel.Navigate(wx.NavigationKeyEvent.IsBackward)
        return True
    if index < len(controls) - 1:
        controls[index + 1].SetFocus()
        return True
    panel.Navigate(wx.NavigationKeyEvent.IsForward)
    return True


def focus_content_area(panel) -> bool:
    if panel._mode == "edit":
        panel._edit_ctrl.SetFocus()
        return True
    if panel._mode == "read":
        if panel._read_text_ctrl:
            panel._read_text_ctrl.SetFocus()
            return True
        panel._read_panel.SetFocus()
        return True
    return False


def activate_toolbar_control(panel, window: wx.Window | None) -> bool:
    if window is None:
        return False
    buttons: list[wx.Button] = [
        panel._mode_button,
        panel._insert_button,
        panel._load_button,
        panel._save_button,
    ]
    if panel._line_length_apply:
        buttons.append(panel._line_length_apply)
    for button in buttons:
        if window is button:
            event = wx.CommandEvent(wx.EVT_BUTTON.typeId, button.GetId())
            event.SetEventObject(button)
            button.GetEventHandler().ProcessEvent(event)
            return True
    return False


def handle_toolbar_char_hook(panel, event: wx.KeyEvent) -> None:
    keycode = event.GetKeyCode()
    if keycode == wx.WXK_SPACE and not event.ControlDown() and not event.AltDown():
        panel._suppress_play_shortcut = True
        event.Skip()
        return
    if keycode == wx.WXK_TAB and not event.ControlDown() and not event.AltDown():
        if move_within_toolbar(panel, event.GetEventObject(), backwards=event.ShiftDown()):
            event.StopPropagation()
            return
    event.Skip()

