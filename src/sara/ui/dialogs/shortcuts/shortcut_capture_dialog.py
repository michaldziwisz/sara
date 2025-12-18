"""Dialog used to capture a new keyboard shortcut."""

from __future__ import annotations

import wx

from sara.core.i18n import gettext as _
from sara.ui.shortcut_utils import accelerator_to_string, format_shortcut_display

_RAW_CTRL_KEYCODES = tuple(
    key
    for key in (
        getattr(wx, "WXK_RAW_CONTROL", None),
        getattr(wx, "WXK_RAW_CTRL", None),
    )
    if key is not None
)

class ShortcutCaptureDialog(wx.Dialog):
    """Let the user press a new key combination."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, title=_("New shortcut"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._captured: str = ""

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        instruction = wx.StaticText(
            self,
            label=_("Press the desired key combination. Press Esc to cancel."),
        )
        main_sizer.Add(instruction, 0, wx.ALL, 10)

        self._display = wx.TextCtrl(
            self,
            value="—",
            style=wx.TE_CENTER | wx.TE_READONLY | wx.BORDER_SIMPLE | wx.WANTS_CHARS,
        )
        font = self._display.GetFont()
        font.MakeBold()
        self._display.SetFont(font)
        self._display.SetMinSize((260, self._display.GetCharHeight() * 2))
        main_sizer.Add(self._display, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self._ok_button = None
        button_sizer = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if button_sizer:
            main_sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 10)
            self._ok_button = self.FindWindowById(wx.ID_OK, self)
            if self._ok_button:
                self._ok_button.Enable(False)

        self.SetSizerAndFit(main_sizer)
        self.CentreOnParent()

        self._bind_key_events(self)
        self._bind_key_events(self._display)
        self.Bind(wx.EVT_SHOW, self._ensure_focus)
        wx.CallAfter(self._focus_capture_panel)

    def _bind_key_events(self, window: wx.Window) -> None:
        window.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        window.Bind(wx.EVT_KEY_DOWN, self._on_key)

    def _ensure_focus(self, event: wx.ShowEvent) -> None:
        if event.IsShown():
            self._focus_capture_panel()
        event.Skip()

    def _focus_capture_panel(self) -> None:
        if self._display:
            self._display.SetFocus()
            self._display.SetSelection(-1, -1)

    def _on_key(self, event: wx.KeyEvent) -> None:
        keycode = event.GetKeyCode()
        if keycode in (wx.WXK_ESCAPE,):
            self._captured = ""
            self.EndModal(wx.ID_CANCEL)
            return

        if keycode in (wx.WXK_SHIFT, wx.WXK_ALT, wx.WXK_CONTROL, *_RAW_CTRL_KEYCODES):
            return

        modifiers = 0
        if event.ControlDown() or event.RawControlDown():
            modifiers |= wx.ACCEL_CTRL
        if event.AltDown():
            modifiers |= wx.ACCEL_ALT
        if event.ShiftDown():
            modifiers |= wx.ACCEL_SHIFT

        shortcut = accelerator_to_string(modifiers, keycode)
        if not shortcut:
            event.Skip()
            return

        self._captured = shortcut
        self._display.SetValue(format_shortcut_display(shortcut) or shortcut)
        if self._ok_button:
            self._ok_button.Enable(True)
        event.Skip(False)

    def get_shortcut(self) -> str:
        return self._captured
