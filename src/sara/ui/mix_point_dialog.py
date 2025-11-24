"""Dialog for editing cue/intro/segue/outro mix points with PFL preview."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import Callable, Dict, Optional
import time

import wx

from sara.core.i18n import gettext as _
from sara.core.loudness import LoudnessStandard, analyze_loudness, find_bs1770gain
from sara.ui.speech import speak_text


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
    _FINE_STEP = 0.01

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
        on_preview: Callable[[float, tuple[float, float] | None], bool],
        on_mix_preview: Callable[[], bool] | None = None,
        on_stop_preview: Callable[[], None],
        track_path: Path,
        initial_replay_gain: float | None,
        on_replay_gain_update: Callable[[float | None], None] | None = None,
        loop_start_seconds: float | None = None,
        loop_end_seconds: float | None = None,
        loop_enabled: bool = False,
        loop_auto_enabled: bool = False,
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
        self._track_path = track_path
        self._current_replay_gain = initial_replay_gain
        self._on_replay_gain_update = on_replay_gain_update
        self._normalizing = False
        self._loop_start = loop_start_seconds or 0.0
        self._loop_end = loop_end_seconds if loop_end_seconds is not None else max(self._loop_start + 0.1, 0.1)
        if self._loop_end <= self._loop_start:
            self._loop_end = self._loop_start + 0.1
        loop_defined = loop_start_seconds is not None and loop_end_seconds is not None
        self._loop_start_defined = loop_defined
        self._loop_end_defined = loop_defined
        self._loop_auto_enabled = loop_auto_enabled or False

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
        self._on_mix_preview = on_mix_preview

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
                "Shortcuts: A/S/Z = move back (5s/1s/0.01s), "
                "F/G/C = move forward (1s/5s/0.01s), D = play/pause, "
                "Q = preview from start, W = preview last 20s, X = capture point, "
                "Z/C fine-tune active point, "
                "V = preview active point, Shift+V = preview loop end, Alt+V = preview loop."
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
        self._create_point_row(
            list_sizer,
            key="loop_start",
            label=_("Loop start"),
            value=self._loop_start,
            mode="absolute",
            allow_assign=True,
            checked=self._loop_start_defined,
        )
        self._create_point_row(
            list_sizer,
            key="loop_end",
            label=_("Loop end"),
            value=self._loop_end,
            mode="absolute",
            allow_assign=True,
            checked=self._loop_end_defined,
        )
        points_box.Add(list_sizer, 1, wx.EXPAND | wx.ALL, 4)

        # auto-enable loop on start toggle
        self._loop_auto_checkbox = wx.CheckBox(self, label=_("Enable loop automatically when loading"))
        self._loop_auto_checkbox.SetValue(bool(self._loop_auto_enabled))
        points_box.Add(self._loop_auto_checkbox, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        help_text = wx.StaticText(
            self,
            label=_(
                "When assigning overlap from the current position, the remaining tail "
                "duration (track end minus cursor) is used."
            ),
        )
        help_text.Wrap(520)
        points_box.Add(help_text, 0, wx.ALL | wx.EXPAND, 4)
        self._loop_preview_button = wx.Button(self, label=_("Preview loop/mix (Alt+V)"))
        points_box.Add(self._loop_preview_button, 0, wx.ALL | wx.ALIGN_RIGHT, 4)
        main_sizer.Add(points_box, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        normalization_box = wx.StaticBoxSizer(wx.StaticBox(self, label=_("Loudness normalization")), wx.VERTICAL)
        gain_row = wx.BoxSizer(wx.HORIZONTAL)
        gain_row.Add(wx.StaticText(self, label=_("Current ReplayGain:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self._replay_gain_display = wx.TextCtrl(
            self,
            value=self._format_replay_gain_text(),
            style=wx.TE_READONLY | wx.BORDER_SIMPLE,
        )
        self._replay_gain_display.SetBackgroundColour(self.GetBackgroundColour())
        self._replay_gain_display.SetName(_("Current ReplayGain value"))
        gain_row.Add(self._replay_gain_display, 1, wx.ALIGN_CENTER_VERTICAL)
        normalization_box.Add(gain_row, 0, wx.ALL | wx.EXPAND, 4)
        choices = [
            _("EBU R128 (-23 LUFS)"),
            _("ATSC A/85 (-24 LUFS)"),
        ]
        self._standard_radio = wx.RadioBox(
            self,
            label=_("Target standard"),
            choices=choices,
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        normalization_box.Add(self._standard_radio, 0, wx.ALL, 4)
        self._normalize_button = wx.Button(self, label=_("Normalize (bs1770gain)"))
        self._normalize_button.Bind(wx.EVT_BUTTON, self._handle_normalize)
        normalization_box.Add(self._normalize_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        self._normalize_status = wx.TextCtrl(
            self,
            value="",
            style=wx.TE_READONLY | wx.TE_MULTILINE | wx.BORDER_SIMPLE,
        )
        self._normalize_status.SetBackgroundColour(self.GetBackgroundColour())
        self._normalize_status.SetName(_("Loudness analysis status"))
        self._normalize_status.SetMinSize((-1, 60))
        normalization_box.Add(self._normalize_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)
        self._replay_gain_display.MoveBeforeInTabOrder(self._standard_radio)
        self._normalize_status.MoveAfterInTabOrder(self._normalize_button)
        self._set_loudness_status(self._initial_loudness_status())
        main_sizer.Add(normalization_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

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
        checked: Optional[bool] = None,
    ) -> None:
        row_sizer = wx.BoxSizer(wx.HORIZONTAL)

        checkbox = wx.CheckBox(self, label=self._format_point_label(label, value))
        checkbox.SetValue((value is not None) if checked is None else checked)
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

        if not checkbox.GetValue():
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
        if key == "overlap":
            spin.SetRange(0.0, max(self._duration or 0.0, 0.0))
        spin.Bind(wx.EVT_SPINCTRLDOUBLE, lambda _evt, row_key=key: self._handle_spin_edit(row_key))
        spin.Bind(wx.EVT_TEXT, lambda _evt, row_key=key: self._handle_spin_edit(row_key))
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
        self._loop_preview_button.Bind(wx.EVT_BUTTON, self._handle_loop_or_mix_preview)

    def _install_shortcuts(self) -> None:
        entries: list[tuple[int, int, int]] = []

        def bind(letter: str, handler: Callable[[], None], *, flags: int = wx.ACCEL_NORMAL) -> None:
            cmd_id = wx.NewIdRef()
            entries.append((flags, ord(letter), int(cmd_id)))
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

    # endregion

    # region preview helpers

    def _start_preview(self) -> None:
        loop_range = self._current_loop_range()
        start = loop_range[0] if loop_range else self._current_position()
        self._play_from(start, loop_range)

    def _toggle_preview(self) -> None:
        if self._preview_active:
            self._stop_preview()
        else:
            self._start_preview()

    def _start_preview_from(self, seconds: float) -> None:
        self._set_position(seconds, restart_preview=False)
        self._play_from(max(0.0, min(seconds, self._duration if self._duration > 0 else seconds)))

    def _play_from(self, seconds: float, loop_range: tuple[float, float] | None = None) -> None:
        if self._on_preview(seconds, loop_range):
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

    def _assign_from_current(self, key: str, position: float | None = None) -> None:
        if position is None:
            position = self._current_position()
        row = self._rows[key]
        if row.mode == "duration":
            value = max(0.0, self._duration - position)
        else:
            value = position
        if key == "overlap":
            value = min(value, self._max_allowed_overlap())
        row.spin.SetValue(value)
        if not row.checkbox.GetValue():
            row.checkbox.SetValue(True)
            self._toggle_point(key)

    def _assign_active_point(self, *, position: float | None = None) -> None:
        key = self._ensure_active_row()
        if not key:
            return
        self._assign_from_current(key, position=position)
        if key in {"loop_start", "loop_end"}:
            self._ensure_loop_consistency()

    def _loop_rows(self) -> tuple[_MixPointRow, _MixPointRow] | None:
        start_row = self._rows.get("loop_start")
        end_row = self._rows.get("loop_end")
        if start_row is None or end_row is None:
            return None
        return start_row, end_row

    def _handle_loop_preview(self, _event: wx.Event) -> None:
        self._start_loop_preview(show_error=True)

    def _handle_loop_or_mix_preview(self, _event: wx.Event | None = None) -> None:
        # zatrzymaj ewentualny bieżący podgląd zanim wystartuje nowy
        if self._preview_active:
            self._on_stop_preview()
            self._preview_active = False
        active_key = self._ensure_active_row()
        if active_key in {"segue", "overlap"} and self._on_mix_preview:
            self._preview_active = False  # oznacz nowy start
            ok = self._on_mix_preview()
            if not ok:
                wx.Bell()
            return
        self._start_loop_preview(show_error=True)

    def _preview_loop_range(self) -> None:
        self._start_loop_preview(show_error=False)

    def _start_loop_preview(self, *, show_error: bool) -> None:
        loop_range = self._current_loop_range()
        if not loop_range:
            if show_error:
                wx.MessageBox(_("Set valid loop start and end first."), _("Error"), parent=self)
            else:
                wx.Bell()
            return
        self._set_position(loop_range[0])
        self._play_from(loop_range[0], loop_range)

    def _current_loop_range(self) -> tuple[float, float] | None:
        rows = self._loop_rows()
        if not rows:
            return None
        start_row, end_row = rows
        if not (start_row.checkbox.GetValue() and end_row.checkbox.GetValue()):
            return None
        start = float(start_row.spin.GetValue())
        end = float(end_row.spin.GetValue())
        if end <= start:
            return None
        return start, end

    def _format_replay_gain_text(self) -> str:
        if self._current_replay_gain is None:
            return _("not set")
        return _("{gain:+.2f} dB").format(gain=self._current_replay_gain)

    def _update_replay_gain_display(self) -> None:
        if hasattr(self, "_replay_gain_display"):
            self._replay_gain_display.ChangeValue(self._format_replay_gain_text())

    def _initial_loudness_status(self) -> str:
        if self._current_replay_gain is None:
            return _("ReplayGain not measured yet")
        return _("Existing ReplayGain: {gain:+.2f} dB").format(gain=self._current_replay_gain)

    def _handle_normalize(self, _event: wx.CommandEvent) -> None:
        if self._normalizing:
            return
        if find_bs1770gain() is None:
            wx.MessageBox(
                _("bs1770gain is not available. Install it and ensure it is on PATH."),
                _("Error"),
                parent=self,
            )
            return
        self._normalizing = True
        self._normalize_button.Enable(False)
        self._set_loudness_status(_("Analyzing loudness…"))
        Thread(target=self._normalization_worker, daemon=True).start()

    def _normalization_worker(self) -> None:
        try:
            standard = self._selected_standard()
            measurement = analyze_loudness(self._track_path, standard=standard)
            target = -23.0 if standard is LoudnessStandard.EBU else -24.0
            gain = target - measurement.integrated_lufs
        except Exception as exc:  # pylint: disable=broad-except
            wx.CallAfter(self._on_normalize_error, str(exc))
        else:
            wx.CallAfter(self._on_normalize_success, gain, measurement.integrated_lufs)

    def _on_normalize_success(self, gain_db: float, measured_lufs: float) -> None:
        self._normalizing = False
        self._normalize_button.Enable(True)
        self._current_replay_gain = gain_db
        self._update_replay_gain_display()
        self._set_loudness_status(
            _("Measured {lufs:.2f} LUFS, applied gain {gain:+.2f} dB").format(
                lufs=measured_lufs,
                gain=gain_db,
            ),
            speak=True,
        )
        if self._on_replay_gain_update:
            self._on_replay_gain_update(gain_db)

    def _on_normalize_error(self, message: str) -> None:
        self._normalizing = False
        self._normalize_button.Enable(True)
        self._set_loudness_status(message, speak=True)
        wx.MessageBox(message or _("Normalization failed"), _("Error"), parent=self)

    def _set_loudness_status(self, message: str, *, speak: bool = False) -> None:
        if hasattr(self, "_normalize_status"):
            self._normalize_status.ChangeValue(message)
        if speak and message:
            speak_text(message)

    def _selected_standard(self) -> LoudnessStandard:
        if self._standard_radio.GetSelection() == 1:
            return LoudnessStandard.ATSC
        return LoudnessStandard.EBU

    def _format_point_label(self, base: str, value: Optional[float]) -> str:
        if value is None:
            return base
        return f"{base} ({value:.3f}s)"

    def _update_point_label(self, key: str) -> None:
        row = self._rows[key]
        value = float(row.spin.GetValue()) if row.checkbox.GetValue() else None
        row.checkbox.SetLabel(self._format_point_label(row.base_label, value))

    def _handle_spin_edit(self, key: str) -> None:
        if key in {"overlap", "segue", "cue"}:
            self._clamp_overlap_spin()
        self._update_point_label(key)
        if key in {"loop_start", "loop_end"}:
            self._ensure_loop_consistency()

    def _current_cue_value(self) -> float:
        cue_row = self._rows.get("cue")
        if cue_row and cue_row.checkbox.GetValue():
            return float(cue_row.spin.GetValue())
        return self._cue_base

    def _current_segue_value(self) -> float:
        segue_row = self._rows.get("segue")
        if segue_row and segue_row.checkbox.GetValue():
            return float(segue_row.spin.GetValue())
        return 0.0

    def _max_allowed_overlap(self) -> float:
        cue_val = self._current_cue_value()
        segue_val = self._current_segue_value()
        return max(0.0, (self._duration or 0.0) - cue_val - max(0.0, segue_val))

    def _clamp_overlap_spin(self) -> None:
        overlap_row = self._rows.get("overlap")
        if not overlap_row:
            return
        max_overlap = self._max_allowed_overlap()
        overlap_row.spin.SetRange(0.0, max_overlap if max_overlap > 0 else 0.0)
        if overlap_row.checkbox.GetValue():
            value = float(overlap_row.spin.GetValue())
            if value > max_overlap:
                overlap_row.spin.SetValue(max_overlap)
                self._update_point_label("overlap")

    def _toggle_point(self, key: str) -> None:
        row = self._rows[key]
        self._active_row_key = key
        enabled = row.checkbox.GetValue()
        self._set_row_enabled(row, enabled)
        self._update_point_label(key)
        if key in {"loop_start", "loop_end"}:
            self._handle_loop_toggle(key, enabled)

    def _set_active_row(self, key: str) -> None:
        self._active_row_key = key
        self._update_point_label(key)

    def _set_row_enabled(self, row: _MixPointRow, enabled: bool) -> None:
        row.spin.Enable(enabled)
        if row.assign_button:
            row.assign_button.Enable(enabled)

    def _handle_loop_toggle(self, key: str, enabled: bool) -> None:
        rows = self._loop_rows()
        if not rows:
            return
        start_row, end_row = rows
        if key == "loop_start":
            if not enabled and end_row.checkbox.GetValue():
                end_row.checkbox.SetValue(False)
                self._set_row_enabled(end_row, False)
                self._update_point_label("loop_end")
            else:
                self._ensure_loop_consistency()
        elif key == "loop_end":
            if enabled and not start_row.checkbox.GetValue():
                start_row.checkbox.SetValue(True)
                self._set_row_enabled(start_row, True)
                self._update_point_label("loop_start")
            if not enabled:
                return
            self._ensure_loop_consistency()

    def _ensure_loop_consistency(self) -> None:
        rows = self._loop_rows()
        if not rows:
            return
        start_row, end_row = rows
        if not start_row.checkbox.GetValue():
            if end_row.checkbox.GetValue():
                end_row.checkbox.SetValue(False)
                self._set_row_enabled(end_row, False)
                self._update_point_label("loop_end")
            return
        if not end_row.checkbox.GetValue():
            return
        start_val = float(start_row.spin.GetValue())
        end_val = float(end_row.spin.GetValue())
        if end_val <= start_val:
            adjusted = start_val + self._FINE_STEP
            end_row.spin.SetValue(adjusted)
            self._update_point_label("loop_end")

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

    def _preview_loop_endpoint(self, *, is_start: bool) -> None:
        rows = self._loop_rows()
        if not rows:
            wx.Bell()
            return
        start_row, end_row = rows
        target_row = start_row if is_start else end_row
        if not target_row.checkbox.GetValue():
            wx.Bell()
            return
        target_value = float(target_row.spin.GetValue())
        if not is_start:
            start_value = float(start_row.spin.GetValue())
            if target_value <= start_value:
                wx.Bell()
                return
        self._start_preview_from(target_value)

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
            # ruch punktu kończy bieżący podgląd
            self._stop_preview()
            self._set_position(target, restart_preview=False)
            self._assign_active_point(position=target)
            return
        self._stop_preview()
        self._set_position(self._current_position() + delta, restart_preview=False)

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
            if key == "overlap":
                value = min(value, self._max_allowed_overlap())
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

        loop_range = self._current_loop_range()
        results["loop"] = {
            "enabled": bool(loop_range),
            "start": loop_range[0] if loop_range else None,
            "end": loop_range[1] if loop_range else None,
        }
        results["loop_auto_enabled"] = bool(self._loop_auto_checkbox.GetValue()) if loop_range else False
        return results
