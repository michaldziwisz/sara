"""UI mixin for event/shortcut wiring in the mix point dialog."""

from __future__ import annotations

from typing import Callable

import wx


class MixPointEventsMixin:
    def _bind_events(self) -> None:
        self._position_slider.Bind(wx.EVT_SLIDER, self._handle_slider_move)
        self._position_ctrl.Bind(wx.EVT_SPINCTRLDOUBLE, self._handle_spin_change)
        self._position_ctrl.Bind(wx.EVT_TEXT, self._handle_spin_change)

        self._play_button.Bind(wx.EVT_BUTTON, lambda _evt: self._start_preview())
        self._stop_button.Bind(wx.EVT_BUTTON, lambda _evt: self._stop_preview())
        self._jump_start_button.Bind(wx.EVT_BUTTON, lambda _evt: self._set_position(0.0, restart_preview=True))
        self._jump_cue_button.Bind(wx.EVT_BUTTON, lambda _evt: self._set_position(self._cue_base, restart_preview=True))
        self._jump_before_end_button.Bind(
            wx.EVT_BUTTON,
            lambda _evt: self._set_position(max(0.0, self._duration - self._DEFAULT_JUMP_SECONDS), restart_preview=True),
        )
        self._nudge_back_small.Bind(wx.EVT_BUTTON, lambda _evt: self._nudge_position(-1.0))
        self._nudge_back_large.Bind(wx.EVT_BUTTON, lambda _evt: self._nudge_position(-5.0))
        self._nudge_forward_small.Bind(wx.EVT_BUTTON, lambda _evt: self._nudge_position(1.0))
        self._nudge_forward_large.Bind(wx.EVT_BUTTON, lambda _evt: self._nudge_position(5.0))
        self.Bind(wx.EVT_BUTTON, self._handle_ok, id=wx.ID_OK)
        self._loop_preview_button.Bind(wx.EVT_BUTTON, self._handle_loop_or_mix_preview)

    def _install_shortcuts(self) -> None:
        entries: list[tuple[int, int, int]] = []

        def bind(letter: str, handler: Callable[[], None], *, flags: int = wx.ACCEL_NORMAL) -> None:
            cmd_id = wx.NewIdRef()
            keycodes: set[int] = set()
            if len(letter) == 1:
                upper = letter.upper()
                lower = letter.lower()
                keycodes.add(ord(upper))
                if lower != upper:
                    keycodes.add(ord(lower))
            else:
                keycodes.add(ord(letter))
            for code in keycodes:
                entries.append((flags, code, int(cmd_id)))
            self.Bind(wx.EVT_MENU, lambda _evt, fn=handler: fn(), id=int(cmd_id))

        def bind_with_shift(letter: str, handler: Callable[[], None]) -> None:
            bind(letter, handler, flags=wx.ACCEL_NORMAL)
            bind(letter, handler, flags=wx.ACCEL_SHIFT)

        bind_with_shift("A", lambda: self._nudge_position(-5.0))
        bind_with_shift("S", lambda: self._nudge_position(-1.0))
        bind_with_shift("F", lambda: self._nudge_position(1.0))
        bind_with_shift("G", lambda: self._nudge_position(5.0))
        bind("Z", lambda: self._nudge_position(-self._FINE_STEP, assign=True), flags=wx.ACCEL_NORMAL)
        bind("C", lambda: self._nudge_position(self._FINE_STEP, assign=True), flags=wx.ACCEL_NORMAL)
        bind("X", self._assign_active_point, flags=wx.ACCEL_NORMAL)
        bind_with_shift("D", self._toggle_preview)
        bind_with_shift("Q", lambda: self._start_preview_from(0.0))
        bind_with_shift(
            "W",
            lambda: self._start_preview_from(max(0.0, (self._duration or 0.0) - self._DEFAULT_JUMP_SECONDS)),
        )
        bind("V", self._preview_active_point, flags=wx.ACCEL_NORMAL)
        bind("V", lambda: self._preview_loop_endpoint(is_start=False), flags=wx.ACCEL_SHIFT)
        bind("V", self._handle_loop_or_mix_preview, flags=wx.ACCEL_ALT)

        accel = wx.AcceleratorTable(entries)
        self.SetAcceleratorTable(accel)

    def _handle_slider_move(self, _event: wx.Event) -> None:
        value = self._position_slider.GetValue() / self._SLIDER_SCALE
        self._sync_position_controls(value)
        if self._preview_active:
            self._play_from(value)

    def _handle_spin_change(self, _event: wx.Event) -> None:
        value = max(
            0.0,
            min(self._position_ctrl.GetValue(), self._duration if self._duration > 0 else self._position_ctrl.GetValue()),
        )
        self._sync_position_controls(value)

    def _handle_ok(self, event: wx.Event) -> None:
        self._stop_preview()
        event.Skip()

    def _handle_close(self, event: wx.CloseEvent) -> None:
        self._stop_preview()
        event.Skip()

    def _handle_char_hook(self, event: wx.KeyEvent) -> None:
        keycode = event.GetKeyCode()
        focus = wx.Window.FindFocus()
        if isinstance(focus, wx.CheckBox) and keycode == wx.WXK_SPACE:
            event.Skip()
            return
        if keycode == wx.WXK_SPACE:
            event.Skip()
            return
        modifiers = event.GetModifiers()
        if keycode == wx.WXK_HOME:
            if modifiers & wx.MOD_SHIFT:
                self._set_position(self._cue_base, restart_preview=True)
            else:
                self._set_position(0.0, restart_preview=True)
            return
        if keycode == wx.WXK_END:
            if modifiers & wx.MOD_SHIFT:
                self._set_position(max(0.0, self._duration - self._DEFAULT_JUMP_SECONDS), restart_preview=True)
            else:
                self._set_position(self._duration, restart_preview=True)
            return
        if keycode in (wx.WXK_LEFT, wx.WXK_RIGHT):
            amount = 0.1
            if modifiers & wx.MOD_SHIFT:
                amount = 1.0
            if modifiers & wx.MOD_CONTROL:
                amount = 5.0
            if keycode == wx.WXK_LEFT:
                amount *= -1
            self._nudge_position(amount)
            return
        event.Skip()

