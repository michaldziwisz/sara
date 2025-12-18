"""Dialog for editing cue/intro/segue/outro mix points with PFL preview."""

from __future__ import annotations

import logging

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional
import time

import wx

logger = logging.getLogger(__name__)

from sara.core.i18n import gettext as _
from sara.ui.dialogs.mix_point_loudness_ui import MixPointLoudnessMixin
from sara.ui.dialogs.mix_point_editor_helpers_ui import MixPointEditorHelpersMixin
from sara.ui.dialogs.mix_point_position_ui import MixPointPositionMixin


@dataclass
class _MixPointRow:
    checkbox: wx.CheckBox
    spin: wx.SpinCtrlDouble
    assign_button: Optional[wx.Button]
    mode: str  # absolute / relative / duration
    base_label: str


class MixPointEditorDialog(MixPointLoudnessMixin, MixPointPositionMixin, MixPointEditorHelpersMixin, wx.Dialog):
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
        segue_fade_seconds: float | None,
        overlap_seconds: float | None,
        on_preview: Callable[[float, tuple[float, float] | None], bool],
        on_mix_preview: Callable[[Dict[str, Optional[float]]], bool] | None = None,
        on_stop_preview: Callable[[], None],
        track_path: Path,
        initial_replay_gain: float | None,
        on_replay_gain_update: Callable[[float | None], None] | None = None,
        loop_start_seconds: float | None = None,
        loop_end_seconds: float | None = None,
        loop_enabled: bool = False,
        loop_auto_enabled: bool = False,
        default_fade_seconds: float = 0.0,
    ) -> None:
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._duration = max(0.0, duration_seconds)
        self._cue_base = cue_in_seconds or 0.0
        self._initial_values: Dict[str, Optional[float]] = {
            "cue": cue_in_seconds,
            "intro": intro_seconds,
            "outro": outro_seconds,
            "segue": segue_seconds,
            "segue_fade": segue_fade_seconds,
            "overlap": overlap_seconds,
        }
        self._on_preview = on_preview
        self._on_stop_preview = on_stop_preview
        self._preview_active = False
        self._track_path = track_path
        self._current_replay_gain = initial_replay_gain
        self._on_replay_gain_update = on_replay_gain_update
        self._normalizing = False
        self._default_fade_duration = max(0.0, default_fade_seconds)
        self._segue_preview_timer: wx.CallLater | None = None
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
        self._mix_preview_running = False

        self._suppress_auto_preview = True
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
        self._suppress_auto_preview = False

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
            key="segue_fade",
            label=_("Segue fade duration"),
            value=self._initial_values["segue_fade"],
            mode="duration",
            allow_assign=False,
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
        if key in {"overlap", "segue_fade"}:
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
        self._cancel_segue_preview_timer()
        loop_range = self._current_loop_range()
        start = loop_range[0] if loop_range else self._current_position()
        self._play_from(start, loop_range)

    def _toggle_preview(self) -> None:
        if self._preview_active:
            self._stop_preview()
        else:
            self._start_preview()

    def _start_preview_from(self, seconds: float) -> None:
        self._cancel_segue_preview_timer()
        self._set_position(seconds, restart_preview=False)
        self._play_from(max(0.0, min(seconds, self._duration if self._duration > 0 else seconds)))

    def _play_from(self, seconds: float, loop_range: tuple[float, float] | None = None) -> None:
        self._cancel_segue_preview_timer()
        self._mix_preview_running = False
        if self._on_preview(seconds, loop_range):
            self._preview_anchor_seconds = seconds
            self._preview_anchor_started = time.perf_counter()
            self._current_cursor_seconds = seconds
            self._preview_active = True
            self._update_preview_buttons()

    def _stop_preview(self) -> None:
        self._cancel_segue_preview_timer()
        self._mix_preview_running = False
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

    def _cancel_segue_preview_timer(self) -> None:
        if self._segue_preview_timer is not None:
            try:
                self._segue_preview_timer.Stop()
            except Exception:
                pass
            self._segue_preview_timer = None

    def _schedule_segue_preview_stop(self, preview_duration: float) -> None:
        self._cancel_segue_preview_timer()
        if preview_duration <= 0.0:
            return
        delay_ms = max(1, int(preview_duration * 1000))
        self._segue_preview_timer = wx.CallLater(delay_ms, self._on_segue_preview_expired)

    def _on_segue_preview_expired(self) -> None:
        self._segue_preview_timer = None
        self._stop_preview()

    def _preview_segue_window(self, *, force: bool = False) -> None:
        if not force and self._suppress_auto_preview:
            return
        mix_preview = self._on_mix_preview
        if mix_preview is None:
            logger.debug("Mix dialog: no mix preview callback available for segue preview")
            return
        segue_row = self._rows.get("segue")
        if not segue_row or not segue_row.checkbox.GetValue():
            return
        fade_row = self._rows.get("segue_fade")
        fade_len = None
        if fade_row and fade_row.checkbox.GetValue():
            fade_len = max(0.0, float(fade_row.spin.GetValue()))
        if fade_len is None or fade_len <= 0.0:
            fade_len = self._default_fade_duration
        max_window = self._max_allowed_overlap()
        if max_window > 0.0:
            fade_len = min(fade_len, max_window)
        if fade_len <= 0.0:
            logger.debug("Mix dialog: skipping segue preview (fade_len=%.3f)", fade_len)
            return
        pre_window = min(4.0, max(0.5, fade_len))
        values = self._collect_mix_values()
        values["_preview_pre_seconds"] = pre_window
        self._stop_preview()
        self._preview_active = False
        logger.debug(
            "Mix dialog: requesting segue mix preview pre=%.3f fade=%.3f values=%s",
            pre_window,
            fade_len,
            {k: values[k] for k in ("segue", "segue_fade", "overlap") if k in values},
        )
        ok = mix_preview(values)
        self._mix_preview_running = bool(ok)
        if not ok:
            wx.Bell()
            logger.debug("Mix dialog: mix preview callback returned False")
            cue_val = self._current_cue_value()
            segue_val = self._current_segue_value()
            fallback_start = max(0.0, cue_val + segue_val - min(pre_window, fade_len))
            self._start_preview_from(fallback_start)
            return
        self._schedule_segue_preview_stop(pre_window + fade_len)

    # endregion

    def get_result(self) -> Dict[str, Optional[float]]:
        """Return user selections as a dict."""

        results = self._collect_mix_values()

        loop_range = self._current_loop_range()
        results["loop"] = {
            "enabled": bool(loop_range),
            "start": loop_range[0] if loop_range else None,
            "end": loop_range[1] if loop_range else None,
        }
        results["loop_auto_enabled"] = bool(self._loop_auto_checkbox.GetValue()) if loop_range else False
        return results
