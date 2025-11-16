"""Dialog for editing cue/intro/segue/outro mix points with PFL preview."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional
import time

import wx

from sara.core.i18n import gettext as _


@dataclass
class _MixPointRow:
    checkbox: wx.CheckBox
    spin: wx.SpinCtrlDouble
    assign_button: Optional[wx.Button]
    mode: str  # absolute / relative / duration
    base_label: str


class MixPointEditorDialog(wx.Dialog):
    """Interactive panel for cue/intro/segue/outro/overlap editing."""

    _SLIDER_SCALE = 1000  # milliseconds precision
    _DEFAULT_JUMP_SECONDS = 20.0
    _FINE_STEP = 0.1

    def __init__(
        self,
        parent: wx.Window,
        *,
        title: str,
        duration_seconds: float,
        cue_in_seconds: float | None,
        intro_seconds: float | None,
        outro_seconds: float | None,
        segue_seconds: float | None,
        overlap_seconds: float | None,
        on_preview: Callable[[float], bool],
        on_stop_preview: Callable[[], None],
    ) -> None:
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._duration = max(0.0, duration_seconds)
        self._cue_base = cue_in_seconds or 0.0
        self._initial_values: Dict[str, Optional[float]] = {
            "cue": cue_in_seconds,
            "intro": intro_seconds,
            "outro": outro_seconds,
            "segue": segue_seconds,
            "overlap": overlap_seconds,
        }
        self._on_preview = on_preview
        self._on_stop_preview = on_stop_preview
        self._preview_active = False

        self._position_slider = wx.Slider(
            self,
            style=wx.SL_HORIZONTAL | wx.SL_AUTOTICKS,
        )
        slider_max = int(max(self._duration * self._SLIDER_SCALE, self._SLIDER_SCALE))
        self._position_slider.SetRange(0, slider_max)
        self._position_slider.SetTickFreq(max(1, slider_max // 10))
        self._position_ctrl = wx.SpinCtrlDouble(
            self,
            min=0.0,
            max=max(self._duration or 0.0, 24 * 3600.0),
            inc=0.01,
            style=wx.TE_PROCESS_ENTER,
        )
        self._position_ctrl.SetDigits(3)
        self._position_label = wx.StaticText(self, label=self._format_time_label(0.0))

        self._play_button = wx.Button(self, label=_("Play (Space)"))
        self._stop_button = wx.Button(self, label=_("Stop"))
        self._jump_start_button = wx.Button(self, label=_("Start"))
        self._jump_cue_button = wx.Button(self, label=_("Cue in"))
        self._jump_before_end_button = wx.Button(self, label=_("End - 20 s"))
        self._nudge_back_small = wx.Button(self, label=_("−1 s"))
        self._nudge_back_large = wx.Button(self, label=_("−5 s"))
        self._nudge_forward_small = wx.Button(self, label=_("+1 s"))
        self._nudge_forward_large = wx.Button(self, label=_("+5 s"))

        self._rows: Dict[str, _MixPointRow] = {}
        self._active_row_key: Optional[str] = None
        self._point_order: list[str] = []
        self._current_cursor_seconds: float = 0.0
        self._preview_anchor_seconds: float = 0.0
        self._preview_anchor_started: float | None = None

        self._build_layout()
        self._bind_events()
        self._install_shortcuts()
        self._initialise_slider_value(self._cue_base)
        self._update_preview_buttons()
        wx.CallAfter(lambda: self._focus_point_by_index(0))
        if self._point_order:
            self._active_row_key = self._point_order[0]
        self.Bind(wx.EVT_CLOSE, self._handle_close)
        self.Bind(wx.EVT_CHAR_HOOK, self._handle_char_hook)

    # region layout helpers

    def _build_layout(self) -> None:
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        info = wx.StaticText(
            self,
            label=_(
                "Shortcuts: A/S/Z = move back (5s/1s/0.1s), "
                "F/G/C = move forward (1s/5s/0.1s), D = play/pause, "
                "Q = preview from start, W = preview last 20s, X = capture current point."
            ),
        )
        info.Wrap(520)
        main_sizer.Add(info, 0, wx.ALL | wx.EXPAND, 8)

        # position controls
        position_box = wx.StaticBoxSizer(wx.StaticBox(self, label=_("Position")), wx.VERTICAL)
        slider_row = wx.BoxSizer(wx.HORIZONTAL)
        slider_row.Add(self._position_slider, 1, wx.ALL | wx.EXPAND, 4)
        slider_row.Add(self._position_ctrl, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)
        slider_row.Add(self._position_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)
        position_box.Add(slider_row, 0, wx.EXPAND)

        nudge_row = wx.BoxSizer(wx.HORIZONTAL)
        nudge_row.Add(self._jump_start_button, 0, wx.ALL, 2)
        nudge_row.Add(self._jump_cue_button, 0, wx.ALL, 2)
        nudge_row.Add(self._jump_before_end_button, 0, wx.ALL, 2)
        nudge_row.AddStretchSpacer()
        nudge_row.Add(self._nudge_back_large, 0, wx.ALL, 2)
        nudge_row.Add(self._nudge_back_small, 0, wx.ALL, 2)
        nudge_row.Add(self._nudge_forward_small, 0, wx.ALL, 2)
        nudge_row.Add(self._nudge_forward_large, 0, wx.ALL, 2)
        position_box.Add(nudge_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)

        preview_row = wx.BoxSizer(wx.HORIZONTAL)
        preview_row.Add(self._play_button, 0, wx.ALL, 2)
        preview_row.Add(self._stop_button, 0, wx.ALL, 2)
        position_box.Add(preview_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        main_sizer.Add(position_box, 0, wx.ALL | wx.EXPAND, 8)

        # mix point list
        points_box = wx.StaticBoxSizer(wx.StaticBox(self, label=_("Mix points")), wx.VERTICAL)

        list_sizer = wx.BoxSizer(wx.VERTICAL)
        self._create_point_row(
            list_sizer,
            key="cue",
            label=_("Cue in"),
            value=self._initial_values["cue"],
            mode="absolute",
            allow_assign=True,
        )
        self._create_point_row(
            list_sizer,
            key="intro",
            label=_("Intro (absolute seconds)"),
            value=self._initial_values["intro"],
            mode="absolute",
            allow_assign=True,
        )
        self._create_point_row(
            list_sizer,
            key="outro",
            label=_("Outro (absolute seconds)"),
            value=self._initial_values["outro"],
            mode="absolute",
            allow_assign=True,
        )
        segue_display = None
        if self._initial_values["segue"] is not None:
            segue_display = self._cue_base + (self._initial_values["segue"] or 0.0)
        self._create_point_row(
            list_sizer,
            key="segue",
            label=_("Segue start (absolute time)"),
            value=segue_display,
            mode="relative",
            allow_assign=True,
        )
        self._create_point_row(
            list_sizer,
            key="overlap",
            label=_("Overlap duration"),
            value=self._initial_values["overlap"],
            mode="duration",
            allow_assign=True,
        )
        points_box.Add(list_sizer, 1, wx.EXPAND | wx.ALL, 4)

        help_text = wx.StaticText(
            self,
            label=_(
                "When assigning overlap from the current position, the remaining tail "
                "duration (track end minus cursor) is used."
            ),
        )
        help_text.Wrap(520)
        points_box.Add(help_text, 0, wx.ALL | wx.EXPAND, 4)
        main_sizer.Add(points_box, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        # dialog buttons
        button_sizer = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if button_sizer:
            main_sizer.Add(button_sizer, 0, wx.ALL | wx.EXPAND, 8)

        self.SetSizer(main_sizer)
        self.SetMinSize((560, 420))

    def _create_point_row(
        self,
        container: wx.BoxSizer,
        *,
        key: str,
        label: str,
        value: Optional[float],
        mode: str,
        allow_assign: bool,
    ) -> None:
        row_sizer = wx.BoxSizer(wx.HORIZONTAL)

        checkbox = wx.CheckBox(self, label=self._format_point_label(label, value))
        checkbox.SetValue(value is not None)
        spin = wx.SpinCtrlDouble(
            self,
            min=0.0,
            max=max(self._duration or 0.0, 24 * 3600.0),
            inc=0.01,
            style=wx.TE_PROCESS_ENTER,
        )
        spin.SetDigits(3)
        assign_button = wx.Button(self, label=_("Use current")) if allow_assign else None

        if value is not None:
            spin.SetValue(float(value))
        else:
            spin.SetValue(0.0)
            spin.Enable(False)
            if assign_button:
                assign_button.Enable(False)

        checkbox.Bind(wx.EVT_CHECKBOX, lambda evt, row_key=key: self._toggle_point(row_key))
        checkbox.Bind(wx.EVT_CHAR_HOOK, lambda evt, row_key=key: self._handle_checkbox_navigation(evt, row_key))
        spin.Bind(wx.EVT_TEXT_ENTER, lambda _evt: None)
        checkbox.Bind(wx.EVT_SET_FOCUS, lambda _evt, row_key=key: self._set_active_row(row_key))
        spin.Bind(wx.EVT_SET_FOCUS, lambda _evt, row_key=key: self._set_active_row(row_key))

        row_sizer.Add(checkbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        row_sizer.Add(spin, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        row_sizer.Add(wx.StaticText(self, label=_("seconds")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        if assign_button:
            assign_button.Bind(wx.EVT_BUTTON, lambda _evt, row_key=key: self._assign_from_current(row_key))
            assign_button.Bind(wx.EVT_SET_FOCUS, lambda _evt, row_key=key: self._set_active_row(row_key))
            row_sizer.Add(assign_button, 0, wx.ALIGN_CENTER_VERTICAL)
        else:
            row_sizer.AddStretchSpacer()

        self._rows[key] = _MixPointRow(
            checkbox=checkbox,
            spin=spin,
            assign_button=assign_button,
            mode=mode,
            base_label=label,
        )
        spin.Bind(wx.EVT_SPINCTRLDOUBLE, lambda _evt, row_key=key: self._update_point_label(row_key))
        spin.Bind(wx.EVT_TEXT, lambda _evt, row_key=key: self._update_point_label(row_key))
        self._point_order.append(key)

        container.Add(row_sizer, 0, wx.EXPAND | wx.ALL, 2)

    # endregion

    # region events

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

    def _install_shortcuts(self) -> None:
        actions: list[tuple[str, Callable[[], None]]] = [
            ("A", lambda: self._nudge_position(-5.0)),
            ("S", lambda: self._nudge_position(-1.0)),
            ("F", lambda: self._nudge_position(1.0)),
            ("G", lambda: self._nudge_position(5.0)),
            ("Z", lambda: self._nudge_position(-self._FINE_STEP, assign=True)),
            ("C", lambda: self._nudge_position(self._FINE_STEP, assign=True)),
            ("D", self._toggle_preview),
            ("Q", lambda: self._start_preview_from(0.0)),
            ("W", lambda: self._start_preview_from(max(0.0, (self._duration or 0.0) - self._DEFAULT_JUMP_SECONDS))),
            ("X", self._assign_active_point),
            ("V", self._preview_active_point),
        ]
        entries: list[tuple[int, int, int]] = []

        for letter, handler in actions:
            cmd_id = wx.NewIdRef()
            keycode = ord(letter)
            for flags in (wx.ACCEL_NORMAL, wx.ACCEL_SHIFT):
                entries.append((flags, keycode, int(cmd_id)))
            self.Bind(wx.EVT_MENU, lambda _evt, fn=handler: fn(), id=int(cmd_id))

        accel = wx.AcceleratorTable(entries)
        self.SetAcceleratorTable(accel)

    def _handle_slider_move(self, _event: wx.Event) -> None:
        value = self._position_slider.GetValue() / self._SLIDER_SCALE
        self._sync_position_controls(value)
        if self._preview_active:
            self._play_from(value)

    def _handle_spin_change(self, _event: wx.Event) -> None:
        value = max(0.0, min(self._position_ctrl.GetValue(), self._duration if self._duration > 0 else self._position_ctrl.GetValue()))
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
            self._toggle_preview()
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

    # endregion

    # region preview helpers

    def _start_preview(self) -> None:
        self._play_from(self._current_position())

    def _toggle_preview(self) -> None:
        if self._preview_active:
            self._stop_preview()
        else:
            self._start_preview()

    def _start_preview_from(self, seconds: float) -> None:
        self._set_position(seconds, restart_preview=False)
        self._play_from(max(0.0, min(seconds, self._duration if self._duration > 0 else seconds)))

    def _play_from(self, seconds: float) -> None:
        if self._on_preview(seconds):
            self._preview_anchor_seconds = seconds
            self._preview_anchor_started = time.perf_counter()
            self._current_cursor_seconds = seconds
            self._preview_active = True
            self._update_preview_buttons()

    def _stop_preview(self) -> None:
        if not self._preview_active:
            self._on_stop_preview()
            return
        self._preview_active = False
        self._preview_anchor_started = None
        self._on_stop_preview()
        self._update_preview_buttons()

    def _update_preview_buttons(self) -> None:
        self._play_button.Enable(not self._preview_active)
        self._stop_button.Enable(self._preview_active)

    # endregion

    # region mix point helpers

    def _assign_from_current(self, key: str) -> None:
        position = self._current_position()
        row = self._rows[key]
        if row.mode == "duration":
            value = max(0.0, self._duration - position)
        else:
            value = position
        row.spin.SetValue(value)
        if not row.checkbox.GetValue():
            row.checkbox.SetValue(True)
            self._toggle_point(key)

    def _assign_active_point(self) -> None:
        key = self._ensure_active_row()
        if not key:
            return
        self._assign_from_current(key)

    def _format_point_label(self, base: str, value: Optional[float]) -> str:
        if value is None:
            return base
        return f"{base} ({value:.3f}s)"

    def _update_point_label(self, key: str) -> None:
        row = self._rows[key]
        value = float(row.spin.GetValue()) if row.checkbox.GetValue() else None
        row.checkbox.SetLabel(self._format_point_label(row.base_label, value))

    def _toggle_point(self, key: str) -> None:
        row = self._rows[key]
        self._active_row_key = key
        enabled = row.checkbox.GetValue()
        row.spin.Enable(enabled)
        if row.assign_button:
            row.assign_button.Enable(enabled)
        self._update_point_label(key)

    def _set_active_row(self, key: str) -> None:
        self._active_row_key = key
        self._update_point_label(key)

    def _preview_active_point(self) -> None:
        key = self._ensure_active_row()
        if not key:
            return
        row = self._rows[key]
        if not row.checkbox.GetValue():
            return
        value = float(row.spin.GetValue())
        start = value
        if row.mode == "relative":
            cue_base = self._rows["cue"].spin.GetValue() if self._rows["cue"].checkbox.GetValue() else self._cue_base
            start = (cue_base or 0.0) + value
        elif row.mode == "duration":
            start = max(0.0, (self._duration or 0.0) - value)
        self._start_preview_from(start)

    def _handle_checkbox_navigation(self, event: wx.KeyEvent, key: str) -> None:
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_UP:
            self._move_checkbox_focus(key, -1)
            return
        if keycode == wx.WXK_DOWN:
            self._move_checkbox_focus(key, 1)
            return
        event.Skip()

    def _ensure_active_row(self) -> Optional[str]:
        if self._active_row_key and self._active_row_key in self._rows:
            return self._active_row_key
        if self._point_order:
            self._active_row_key = self._point_order[0]
            return self._active_row_key
        return None

    def _move_checkbox_focus(self, key: str, offset: int) -> None:
        if key not in self._point_order:
            return
        index = self._point_order.index(key)
        target = (index + offset) % len(self._point_order)
        self._focus_point_by_index(target)

    def _focus_point_by_index(self, index: int) -> None:
        if not self._point_order:
            return
        index = max(0, min(index, len(self._point_order) - 1))
        key = self._point_order[index]
        row = self._rows.get(key)
        if row:
            row.checkbox.SetFocus()
            self._active_row_key = key

    # endregion

    # region positional helpers

    def _current_position(self) -> float:
        if self._preview_anchor_started is not None:
            elapsed = time.perf_counter() - self._preview_anchor_started
            current = self._preview_anchor_seconds + max(0.0, elapsed)
            if self._duration:
                current = min(current, self._duration)
            return max(0.0, current)
        return self._current_cursor_seconds

    def _sync_position_controls(self, seconds: float) -> None:
        clamped = max(0.0, min(seconds, self._duration if self._duration > 0 else seconds))
        self._current_cursor_seconds = clamped
        self._position_ctrl.SetValue(clamped)
        slider_value = int(round(clamped * self._SLIDER_SCALE))
        self._position_slider.SetValue(slider_value)
        self._position_label.SetLabel(self._format_time_label(clamped))

    def _format_time_label(self, seconds: float) -> str:
        minutes, secs = divmod(int(max(0.0, seconds)), 60)
        return f"{minutes:02d}:{secs:02d}"

    def _set_position(self, seconds: float, *, restart_preview: bool = False) -> None:
        clamped = max(0.0, min(seconds, self._duration if self._duration > 0 else seconds))
        self._sync_position_controls(clamped)
        if restart_preview and self._preview_active:
            self._play_from(clamped)
        else:
            self._current_cursor_seconds = clamped

    def _nudge_position(self, delta: float, *, assign: bool = False) -> None:
        if assign:
            key = self._ensure_active_row()
            if not key:
                self._set_position(self._current_position() + delta, restart_preview=True)
                return
            row = self._rows[key]
            if not row.checkbox.GetValue():
                row.checkbox.SetValue(True)
                self._toggle_point(key)
            reference = row.spin.GetValue()
            if row.mode == "relative":
                cue_base = self._rows["cue"].spin.GetValue() if self._rows["cue"].checkbox.GetValue() else self._cue_base
                reference = (cue_base or 0.0) + reference
            elif row.mode == "duration":
                reference = max(0.0, (self._duration or 0.0) - reference)
            target = reference + delta
            self._set_position(target, restart_preview=True)
            self._assign_active_point()
            return
        self._set_position(self._current_position() + delta, restart_preview=True)

    def _initialise_slider_value(self, seconds: float) -> None:
        if self._duration <= 0:
            seconds = 0.0
            self._position_slider.Disable()
        self._set_position(max(0.0, min(seconds, self._duration if self._duration > 0 else seconds)), restart_preview=False)

    # endregion

    def get_result(self) -> Dict[str, Optional[float]]:
        """Return user selections as a dict."""

        results: Dict[str, Optional[float]] = {}
        final_cue = None

        for key in ("cue", "intro", "outro", "segue", "overlap"):
            row = self._rows[key]
            if not row.checkbox.GetValue():
                results[key] = None
                if key == "cue":
                    final_cue = 0.0
                continue
            value = float(row.spin.GetValue())
            if row.mode == "absolute":
                results[key] = value
                if key == "cue":
                    final_cue = value
            elif row.mode == "relative":
                cue_base = final_cue
                if cue_base is None:
                    cue_row = self._rows["cue"]
                    cue_base = cue_row.spin.GetValue() if cue_row.checkbox.GetValue() else self._cue_base
                results[key] = max(0.0, value - (cue_base or 0.0))
            elif row.mode == "duration":
                results[key] = max(0.0, value)

        return results
