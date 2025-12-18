"""Global keyboard shortcut handlers extracted from the main frame."""

from __future__ import annotations

import wx

from sara.core.i18n import gettext as _


def should_handle_altgr_track_remaining(event: wx.KeyEvent, keycode: int) -> bool:
    if keycode not in (ord("T"), ord("t")):
        return False
    modifiers = event.GetModifiers()
    altgr_flag = getattr(wx, "MOD_ALTGR", None)
    if isinstance(modifiers, int) and altgr_flag and modifiers & altgr_flag:
        return True
    if event.AltDown() and event.ControlDown() and not event.MetaDown():
        return True
    return False


def handle_global_char_hook(frame, event: wx.KeyEvent) -> None:
    keycode = event.GetKeyCode()
    if should_handle_altgr_track_remaining(event, keycode):
        frame._on_track_remaining()
        return
    if keycode == wx.WXK_F6:
        if frame._cycle_playlist_focus(backwards=event.ShiftDown()):
            return
    if handle_jingles_key(frame, event):
        return
    panel, focus = frame._active_news_panel()
    if keycode == wx.WXK_SPACE and panel and panel.is_edit_control(focus):
        event.Skip()
        event.StopPropagation()
        return
    event.Skip()


def handle_jingles_key(frame, event: wx.KeyEvent) -> bool:
    panel = frame._get_current_music_panel()
    if panel is None:
        return False
    focus = wx.Window.FindFocus()
    if not panel.is_list_control(focus):
        return False
    if event.ControlDown() or event.AltDown() or event.MetaDown():
        return False

    keycode = event.GetKeyCode()

    slot_index: int | None = None
    if ord("0") <= keycode <= ord("9"):
        digit = chr(keycode)
        slot_index = 9 if digit == "0" else int(digit) - 1
    else:
        numpad_map = {
            wx.WXK_NUMPAD1: 0,
            wx.WXK_NUMPAD2: 1,
            wx.WXK_NUMPAD3: 2,
            wx.WXK_NUMPAD4: 3,
            wx.WXK_NUMPAD5: 4,
            wx.WXK_NUMPAD6: 5,
            wx.WXK_NUMPAD7: 6,
            wx.WXK_NUMPAD8: 7,
            wx.WXK_NUMPAD9: 8,
            wx.WXK_NUMPAD0: 9,
        }
        slot_index = numpad_map.get(keycode)

    if slot_index is not None:
        overlay = bool(event.ShiftDown())
        if not frame._jingles.play_slot(slot_index, overlay=overlay):
            number_label = "0" if slot_index == 9 else str(slot_index + 1)
            frame._announce_event("jingles", _("Empty jingle slot %s") % number_label)
        event.StopPropagation()
        event.Skip(False)
        return True

    prev_keys = {ord("-"), ord("_"), getattr(wx, "WXK_SUBTRACT", -1)}
    next_keys = {ord("="), ord("+"), getattr(wx, "WXK_ADD", -1)}
    if keycode in prev_keys:
        frame._jingles.prev_page()
        event.StopPropagation()
        event.Skip(False)
        return True
    if keycode in next_keys:
        frame._jingles.next_page()
        event.StopPropagation()
        event.Skip(False)
        return True

    return False

