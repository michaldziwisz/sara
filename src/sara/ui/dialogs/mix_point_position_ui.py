"""UI mixin for position/slider helpers in the mix point dialog."""

from __future__ import annotations

import time


class MixPointPositionMixin:
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
        was_previewing = self._preview_active or self._mix_preview_running
        if assign:
            key = self._ensure_active_row()
            if not key:
                self._stop_preview()
                self._set_position(self._current_position() + delta, restart_preview=False)
                if was_previewing:
                    self._start_preview_from(self._current_cursor_seconds)
                return
            row = self._rows[key]
            if not row.checkbox.GetValue():
                row.checkbox.SetValue(True)
                self._toggle_point(key)
            reference = row.spin.GetValue()
            if row.mode == "duration" and key != "segue_fade":
                reference = max(0.0, (self._duration or 0.0) - reference)
            target = reference + delta
            # ruch punktu kończy bieżący podgląd
            self._stop_preview()
            self._set_position(target, restart_preview=False)
            self._assign_active_point(position=target)
            if key in {"segue", "segue_fade"}:
                self._preview_segue_window()
            elif was_previewing:
                self._start_preview_from(self._current_cursor_seconds)
            return
        self._stop_preview()
        self._set_position(self._current_position() + delta, restart_preview=False)
        if was_previewing:
            self._start_preview_from(self._current_cursor_seconds)

    def _initialise_slider_value(self, seconds: float) -> None:
        if self._duration <= 0:
            seconds = 0.0
            self._position_slider.Disable()
        self._set_position(max(0.0, min(seconds, self._duration if self._duration > 0 else seconds)), restart_preview=False)

