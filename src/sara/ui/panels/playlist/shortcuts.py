"""Keyboard shortcuts handling for the playlist panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

import wx

from sara.core.playlist import PlaylistKind

if TYPE_CHECKING:
    from sara.ui.panels.playlist.panel import PlaylistPanel


def handle_key_down(panel: "PlaylistPanel", event: wx.KeyEvent) -> None:
    if panel._handle_navigation_key(event):
        return
    if not panel._handle_selection_key_event(event):
        event.Skip()


def handle_char_hook(panel: "PlaylistPanel", event: wx.KeyEvent) -> None:
    if panel._handle_navigation_key(event):
        return
    if not panel._handle_selection_key_event(event):
        event.Skip()


def handle_char(panel: "PlaylistPanel", event: wx.KeyEvent) -> None:
    if panel._handle_navigation_key(event):
        return
    if not panel._handle_selection_key_event(event):
        event.Skip()


def handle_list_key_down(panel: "PlaylistPanel", event: wx.ListEvent) -> None:
    key_code = event.GetKeyCode()
    if key_code in (wx.WXK_UP, wx.WXK_DOWN) and not wx.GetKeyState(wx.WXK_SHIFT) and not wx.GetKeyState(wx.WXK_CONTROL) and not wx.GetKeyState(wx.WXK_ALT):
        delta = -1 if key_code == wx.WXK_UP else 1
        if panel._move_focus_by_delta(delta):
            event.Skip(False)
            return
    if not panel._handle_selection_key_event(event):
        event.Skip()


def handle_selection_key_event(panel: "PlaylistPanel", event: wx.KeyEvent | wx.ListEvent) -> bool:
    key_code = event.GetKeyCode()
    allowed_keys = (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
    space_requested = (
        panel._swap_play_select
        and panel.model.kind is PlaylistKind.MUSIC
        and key_code == wx.WXK_SPACE
    )
    if not space_requested and key_code not in allowed_keys:
        return False
    if isinstance(event, wx.KeyEvent):
        if event.ControlDown() or event.AltDown() or event.MetaDown():
            return False
        if event.ShiftDown():
            return False

    index = panel._list_ctrl.GetFocusedItem()
    if index == wx.NOT_FOUND:
        index = panel._list_ctrl.GetFirstSelected()
    if index == wx.NOT_FOUND and panel._list_ctrl.GetItemCount() > 0:
        index = 0

    if index == wx.NOT_FOUND or index >= len(panel.model.items):
        return False

    item = panel.model.items[index]

    if space_requested:
        if panel._on_toggle_selection:
            # wymuś jednoznaczną selekcję na wskazanym elemencie
            panel.set_selection([index], focus=True)
            panel._trigger_selection_toggle(index)
            return True
        return False

    if panel._swap_play_select and panel.model.kind is PlaylistKind.MUSIC and panel._on_play_request:
        panel._notify_focus()
        panel._list_ctrl.Focus(index)
        panel._on_play_request(panel.model.id, item.id)
        return True

    if not panel._on_toggle_selection:
        return False

    panel._trigger_selection_toggle(index)
    return True


def handle_item_activated(panel: "PlaylistPanel", event: wx.ListEvent) -> None:
    if panel._on_toggle_selection:
        panel._trigger_selection_toggle(event.GetIndex())
    event.Skip()


def handle_navigation_key(panel: "PlaylistPanel", event: wx.KeyEvent) -> bool:
    key_code = event.GetKeyCode()
    if key_code not in (wx.WXK_UP, wx.WXK_DOWN):
        return False
    if event.ControlDown() or event.AltDown() or event.MetaDown() or event.ShiftDown():
        return False
    delta = -1 if key_code == wx.WXK_UP else 1
    handled = panel._move_focus_by_delta(delta)
    if handled:
        event.StopPropagation()
        event.Skip(False)
    return handled
