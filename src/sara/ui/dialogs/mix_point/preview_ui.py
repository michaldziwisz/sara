"""UI mixin for preview playback helpers in the mix point dialog."""

from __future__ import annotations

import logging
import time

import wx


logger = logging.getLogger(__name__)


class MixPointPreviewMixin:
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
