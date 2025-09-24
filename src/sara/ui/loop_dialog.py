"""Loop configuration dialog."""

from __future__ import annotations

from typing import Callable

import time

import wx

from sara.core.i18n import gettext as _


class LoopDialog(wx.Dialog):
    """Allow the user to set loop in/out points and preview them."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        duration_seconds: float,
        initial_start: float | None = None,
        initial_end: float | None = None,
        enable_loop: bool = True,
        on_preview: Callable[[float, float], bool] | None = None,
        on_loop_update: Callable[[float, float], bool] | None = None,
        on_preview_stop: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, title=_("Loop configuration"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._duration = max(duration_seconds, 0.0)
        self._on_preview = on_preview
        self._on_preview_stop = on_preview_stop
        self._on_loop_update = on_loop_update
        self._preview_refresh_timer = wx.Timer(self)
        self._pending_preview_refresh = False
        self._preview_min_interval_ms = 80
        self._last_preview_restart = 0.0
        self._cleared = False

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        description = wx.StaticText(
            self,
            label=_("Pick loop start and end times in seconds. Preview plays on the PFL output."),
        )
        description.Wrap(420)
        main_sizer.Add(description, 0, wx.ALL, 10)

        self._enable_checkbox = wx.CheckBox(self, label=_("Enable loop for this track"))
        self._enable_checkbox.SetValue(enable_loop)
        main_sizer.Add(self._enable_checkbox, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        grid = wx.FlexGridSizer(rows=2, cols=2, hgap=10, vgap=10)
        grid.AddGrowableCol(1, 1)

        start_label = wx.StaticText(self, label=_("Start (s):"))
        self._start_ctrl = wx.SpinCtrlDouble(self, min=0.0, max=self._duration or 3600.0, inc=0.01)
        self._start_ctrl.SetDigits(3)
        grid.Add(start_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._start_ctrl, 0, wx.EXPAND)

        end_label = wx.StaticText(self, label=_("End (s):"))
        self._end_ctrl = wx.SpinCtrlDouble(self, min=0.0, max=self._duration or 3600.0, inc=0.01)
        self._end_ctrl.SetDigits(3)
        grid.Add(end_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._end_ctrl, 0, wx.EXPAND)

        main_sizer.Add(grid, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        button_bar = wx.StdDialogButtonSizer()
        self._preview_button = wx.Button(self, label=_("Preview"))
        self._preview_button.SetToolTip(_("Start preview (Ctrl+P)"))
        self._preview_stop_button = wx.Button(self, label=_("Stop preview"))
        self._preview_stop_button.SetToolTip(_("Stop preview (Ctrl+Shift+P)"))
        self._clear_button = wx.Button(self, label=_("Remove loop"))
        self._clear_button.SetToolTip(_("Remove the saved loop and disable looping"))
        button_bar.AddButton(self._preview_button)
        button_bar.AddButton(self._preview_stop_button)
        button_bar.AddButton(self._clear_button)

        self._status_label = wx.StaticText(self, label="")
        button_bar.Add(self._status_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)

        button_bar.AddButton(wx.Button(self, wx.ID_OK))
        button_bar.AddButton(wx.Button(self, wx.ID_CANCEL))
        button_bar.Realize()
        main_sizer.Add(button_bar, 0, wx.EXPAND | wx.ALL, 10)

        self.Bind(wx.EVT_BUTTON, self._handle_preview, self._preview_button)
        self.Bind(wx.EVT_BUTTON, self._handle_preview_stop, self._preview_stop_button)
        self.Bind(wx.EVT_BUTTON, self._handle_clear_loop, self._clear_button)
        self.Bind(wx.EVT_BUTTON, self._handle_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_CHECKBOX, self._sync_controls, self._enable_checkbox)
        self.Bind(wx.EVT_CLOSE, self._handle_close)
        self.Bind(wx.EVT_CHAR_HOOK, self._handle_char_hook)
        self.Bind(wx.EVT_TIMER, self._on_preview_refresh_timer, self._preview_refresh_timer)
        self._start_ctrl.Bind(wx.EVT_SPINCTRLDOUBLE, self._handle_value_change)
        self._start_ctrl.Bind(wx.EVT_TEXT, self._handle_value_change)
        self._start_ctrl.Bind(wx.EVT_KEY_DOWN, self._handle_spin_key)
        self._end_ctrl.Bind(wx.EVT_SPINCTRLDOUBLE, self._handle_value_change)
        self._end_ctrl.Bind(wx.EVT_TEXT, self._handle_value_change)
        self._end_ctrl.Bind(wx.EVT_KEY_DOWN, self._handle_spin_key)

        self._set_initial_values(initial_start, initial_end)
        self._preview_active = False
        self._suspend_value_handler = False
        self._last_start_value = float(self._start_ctrl.GetValue())
        self._last_end_value = float(self._end_ctrl.GetValue())
        self._sync_controls()

        self.SetSizer(main_sizer)
        self.Fit()

    # region helpers

    def _set_initial_values(self, start: float | None, end: float | None) -> None:
        if start is None:
            start = 0.0
        if end is None or end <= start:
            end = min(self._duration if self._duration else start + 5.0, start + 5.0)
        self._start_ctrl.SetValue(max(0.0, start))
        maximum = self._duration if self._duration else max(end, start + 10.0)
        self._start_ctrl.SetRange(0.0, maximum)
        self._end_ctrl.SetRange(0.0, maximum)
        self._end_ctrl.SetValue(max(start + 0.1, end))
        self._last_start_value = float(self._start_ctrl.GetValue())
        self._last_end_value = float(self._end_ctrl.GetValue())

    def _sync_controls(self, _event: wx.Event | None = None) -> None:
        enabled = self._enable_checkbox.GetValue()
        self._start_ctrl.Enable(enabled)
        self._end_ctrl.Enable(enabled)
        self._preview_button.Enable(self._on_preview is not None and not self._cleared)
        self._preview_stop_button.Enable(self._preview_active)
        if hasattr(self, "_clear_button"):
            self._clear_button.Enable(True)

    def _current_values(self) -> tuple[float, float]:
        start = float(self._start_ctrl.GetValue())
        end = float(self._end_ctrl.GetValue())
        return start, end

    def _validate(self) -> bool:
        if not self._enable_checkbox.GetValue():
            return True
        start, end = self._current_values()
        if end <= start:
            wx.MessageBox(_("Loop end must be greater than start."), _("Error"), parent=self)
            return False
        if self._duration and end > self._duration + 0.01:
            wx.MessageBox(_("Loop end exceeds track length."), _("Error"), parent=self)
            return False
        return True

    def _handle_preview(self, _event: wx.Event | None) -> None:
        self._maybe_restart_preview(force=True, show_error=True)

    def _handle_preview_stop(self, _event: wx.Event | None = None) -> None:
        self._cancel_preview_refresh()
        if self._on_preview_stop:
            self._on_preview_stop()
        self._preview_active = False
        self._sync_controls()

    def _handle_ok(self, event: wx.Event) -> None:
        if not self._validate():
            event.Skip(False)
            return
        self._handle_preview_stop(None)
        self.EndModal(wx.ID_OK)

    def _handle_close(self, _event: wx.CloseEvent) -> None:
        self._handle_preview_stop(None)
        self._cancel_preview_refresh()
        self.Destroy()

    def _handle_clear_loop(self, _event: wx.CommandEvent) -> None:
        self._cleared = True
        self._enable_checkbox.SetValue(False)
        self._start_ctrl.SetValue(0.0)
        default_end = min(5.0, self._duration or 5.0)
        self._end_ctrl.SetValue(default_end if default_end > 0.0 else 0.1)
        self._last_start_value = float(self._start_ctrl.GetValue())
        self._last_end_value = float(self._end_ctrl.GetValue())
        self._handle_preview_stop(None)
        self._sync_controls()
        self._status_label.SetLabel(_("Loop removed"))

    def was_cleared(self) -> bool:
        return self._cleared

    def _handle_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetModifiers() == wx.MOD_CONTROL and event.GetKeyCode() in (ord("P"), ord("p")):
            self._handle_preview(event)
            return
        if (
            event.GetModifiers() == (wx.MOD_CONTROL | wx.MOD_SHIFT)
            and event.GetKeyCode() in (ord("P"), ord("p"))
        ):
            self._handle_preview_stop(None)
            return
        event.Skip()

    def _handle_value_change(self, event: wx.Event) -> None:
        if self._suspend_value_handler:
            event.Skip()
            return
        if self._preview_active and self._enable_checkbox.GetValue():
            start, end = self._current_values()
            start_changed = abs(start - self._last_start_value) > 1e-6
            end_changed = abs(end - self._last_end_value) > 1e-6

            if start_changed:
                self._maybe_restart_preview()
            elif end_changed:
                handled = False
                if self._on_loop_update:
                    handled = self._on_loop_update(start, end)
                if not handled:
                    self._maybe_restart_preview()

        self._last_start_value = float(self._start_ctrl.GetValue())
        self._last_end_value = float(self._end_ctrl.GetValue())
        event.Skip()

    def _handle_spin_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        modifiers = event.GetModifiers()

        if key in (wx.WXK_UP, wx.WXK_NUMPAD_UP):
            if modifiers == wx.MOD_CONTROL:
                self._adjust_spin(event.GetEventObject(), +1.0)
                return
            if modifiers == wx.MOD_ALT:
                self._adjust_spin(event.GetEventObject(), +0.01)
                return
            if modifiers == wx.MOD_NONE:
                self._adjust_spin(event.GetEventObject(), +0.1)
                return
        if key in (wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN):
            if modifiers == wx.MOD_CONTROL:
                self._adjust_spin(event.GetEventObject(), -1.0)
                return
            if modifiers == wx.MOD_ALT:
                self._adjust_spin(event.GetEventObject(), -0.01)
                return
            if modifiers == wx.MOD_NONE:
                self._adjust_spin(event.GetEventObject(), -0.1)
                return
        event.Skip()

    def _adjust_spin(self, ctrl: wx.SpinCtrlDouble, delta: float) -> None:
        current = float(ctrl.GetValue())
        minimum = ctrl.GetMin()
        maximum = ctrl.GetMax()
        new_value = min(maximum, max(minimum, current + delta))
        if abs(new_value - current) < 1e-9:
            return
        self._suspend_value_handler = True
        ctrl.SetValue(new_value)
        self._suspend_value_handler = False
        self._handle_value_change(wx.CommandEvent())

    def _maybe_restart_preview(self, *, force: bool = False, show_error: bool = False) -> None:
        if not self._on_preview or not self._enable_checkbox.GetValue():
            return

        start, end = self._current_values()
        over_duration = bool(self._duration) and end > self._duration + 0.01
        if end <= start or over_duration:
            if self._preview_active:
                self._handle_preview_stop(None)
            if show_error:
                self._validate()
            return

        now = time.monotonic()
        elapsed_ms = (now - self._last_preview_restart) * 1000.0
        if not force and elapsed_ms < self._preview_min_interval_ms:
            remaining = max(5, int(self._preview_min_interval_ms - elapsed_ms))
            self._pending_preview_refresh = True
            self._preview_refresh_timer.StartOnce(remaining)
            return

        self._cancel_preview_refresh()
        result = self._on_preview(start, end)
        if result:
            self._preview_active = True
            self._last_preview_restart = time.monotonic()
        else:
            self._preview_active = False
        self._sync_controls()

    def _cancel_preview_refresh(self) -> None:
        if self._preview_refresh_timer.IsRunning():
            self._preview_refresh_timer.Stop()
        self._pending_preview_refresh = False

    def _on_preview_refresh_timer(self, _event: wx.TimerEvent) -> None:
        if not self._pending_preview_refresh:
            return
        self._pending_preview_refresh = False
        self._maybe_restart_preview(force=True)

    # endregion

    def get_result(self) -> tuple[bool, float, float]:
        """Zwraca (loop_enabled, start, end)."""
        start, end = self._current_values()
        return self._enable_checkbox.GetValue(), start, end
