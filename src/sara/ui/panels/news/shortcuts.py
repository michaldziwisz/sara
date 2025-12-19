"""Keyboard shortcuts handler for `NewsPlaylistPanel`."""

from __future__ import annotations

import wx


def handle_char_hook(panel, event: wx.KeyEvent) -> None:
    keycode = event.GetKeyCode()
    target = event.GetEventObject()

    if event.ControlDown() and not event.AltDown():
        if keycode in (ord("E"), ord("e")):
            panel._toggle_mode(None)
            event.StopPropagation()
            return
        if keycode in (ord("O"), ord("o")):
            panel._on_load_service(None)
            event.StopPropagation()
            return
        if keycode in (ord("S"), ord("s")):
            panel._on_save_service(None)
            event.StopPropagation()
            return
        if keycode in (ord("P"), ord("p")):
            if event.ShiftDown():
                panel._edit_controller.stop_preview()
            else:
                panel._edit_controller.preview_audio_at_caret()
            event.StopPropagation()
            return

    if panel._mode == "read":
        focused = wx.Window.FindFocus()
        if focused is panel._read_text_ctrl:
            if panel._handle_read_action(event):
                event.StopPropagation()
                return
            if keycode == wx.WXK_TAB and not event.ControlDown() and not event.AltDown():
                if event.ShiftDown():
                    panel.Navigate(wx.NavigationKeyEvent.IsBackward)
                else:
                    if panel._focus_toolbar_from_text(backwards=False):
                        event.StopPropagation()
                        return
                event.StopPropagation()
                return
        event.Skip()
        return

    if target is not panel._edit_ctrl:
        event.Skip()
        return

    if keycode == wx.WXK_TAB and not event.ControlDown() and not event.AltDown():
        if event.ShiftDown():
            panel.Navigate(wx.NavigationKeyEvent.IsBackward)
        else:
            if panel._focus_toolbar_from_text(backwards=False):
                event.StopPropagation()
                return
        event.StopPropagation()
        return

    if event.ControlDown() and not event.AltDown() and keycode in (ord("V"), ord("v")):
        if panel._edit_controller.paste_audio_from_clipboard(silent_if_empty=True):
            event.StopPropagation()
            return
        # allow default paste behaviour when clipboard has text only

    if not event.ControlDown() and not event.AltDown() and keycode == wx.WXK_SPACE:
        panel._suppress_play_shortcut = True
        panel._edit_ctrl.WriteText(" ")
        event.StopPropagation()
        return

    event.Skip()

