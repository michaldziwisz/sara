"""Read-mode rendering and key handling for `NewsPlaylistPanel`."""

from __future__ import annotations

from pathlib import Path

import wx

from sara.core.i18n import gettext as _


def render_read_panel(panel) -> None:
    wrapper = wx.BoxSizer(wx.VERTICAL)
    for child in panel._read_panel.GetChildren():
        child.Destroy()
    panel._read_text_ctrl = None
    view_model = panel._read_controller.build_view(panel.model.news_markdown or "")
    article_lines = view_model.lines
    audio_entries = view_model.audio_paths

    if article_lines:
        text_value = "\n".join(article_lines)
    else:
        text_value = _("No content. Switch to edit mode to add text.")

    panel._read_text_ctrl = wx.TextCtrl(
        panel._read_panel,
        value=text_value,
        style=wx.TE_READONLY | wx.TE_MULTILINE | wx.BORDER_NONE | wx.TE_PROCESS_TAB,
    )
    panel._read_text_ctrl.Bind(wx.EVT_SET_FOCUS, panel._notify_focus)
    panel._read_text_ctrl.Bind(wx.EVT_CHAR_HOOK, panel._handle_char_hook)
    panel._read_text_ctrl.Bind(wx.EVT_KEY_DOWN, panel._handle_read_key)
    wrapper.Add(panel._read_text_ctrl, 1, wx.EXPAND | wx.ALL, 4)

    for index, path in enumerate(audio_entries, start=1):
        filename = Path(path).name
        button = wx.Button(panel._read_panel, label=_("Play audio %d: %s") % (index, filename))
        button.Bind(wx.EVT_BUTTON, lambda evt, clip=path: panel._play_clip(clip))
        wrapper.Add(button, 0, wx.ALL, 4)

    panel._read_panel.SetSizer(wrapper)
    panel._read_panel.SetupScrolling(scroll_x=False, scroll_y=True)
    panel._restore_caret_position(panel._read_text_ctrl)


def current_read_line(panel) -> int | None:
    if not panel._read_text_ctrl:
        return None
    pos = panel._read_text_ctrl.GetInsertionPoint()
    success, _, line_index = panel._read_text_ctrl.PositionToXY(pos)
    return line_index if success else None


def focus_read_line(panel, line_index: int | None) -> None:
    if line_index is None or not panel._read_text_ctrl:
        return
    pos_target = panel._read_text_ctrl.XYToPosition(0, line_index)
    if pos_target == wx.NOT_FOUND:
        return
    panel._read_text_ctrl.SetInsertionPoint(pos_target)
    panel._read_text_ctrl.ShowPosition(pos_target)
    panel._read_text_ctrl.SetFocus()
    panel._update_caret_from_read()


def handle_read_action(panel, event: wx.KeyEvent) -> bool:
    line_index = current_read_line(panel)
    action = panel._read_controller.handle_key(
        event.GetKeyCode(),
        shift=event.ShiftDown(),
        control=event.ControlDown(),
        alt=event.AltDown(),
        current_line=line_index,
    )
    if action.play_path:
        panel._play_clip(action.play_path)
    if action.focus_line is not None:
        focus_read_line(panel, action.focus_line)
    return action.handled


def handle_read_key(panel, event: wx.KeyEvent) -> None:
    keycode = event.GetKeyCode()
    handled = handle_read_action(panel, event)
    if handled:
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


def play_clip(panel, path_str: str) -> None:
    device_id = panel.model.output_device or (panel.model.output_slots[0] if panel.model.output_slots else None)
    panel._on_play_audio(Path(path_str), device_id)

