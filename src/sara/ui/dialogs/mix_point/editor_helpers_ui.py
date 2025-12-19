"""UI mixin with mix point editing helpers for the mix point dialog."""

from __future__ import annotations

import logging
from typing import Dict, Optional

import wx

from sara.core.i18n import gettext as _


logger = logging.getLogger(__name__)


class MixPointEditorHelpersMixin:
    def _assign_from_current(self, key: str, position: float | None = None) -> None:
        if position is None:
            position = self._current_position()
        row = self._rows[key]
        if key == "segue_fade":
            value = max(0.0, position)
        elif row.mode == "duration":
            value = max(0.0, self._duration - position)
        else:
            value = position
        if key in {"overlap", "segue_fade"}:
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

    def _loop_rows(self) -> tuple["_MixPointRow", "_MixPointRow"] | None:
        start_row = self._rows.get("loop_start")
        end_row = self._rows.get("loop_end")
        if start_row is None or end_row is None:
            return None
        return start_row, end_row

    def _handle_loop_preview(self, _event: wx.Event) -> None:
        self._start_loop_preview(show_error=True)

    def _handle_loop_or_mix_preview(self, _event: wx.Event | None = None) -> None:
        # zatrzymaj ewentualny bieżący podgląd zanim wystartuje nowy
        self._stop_preview()
        active_key = self._ensure_active_row()
        if active_key in {"segue", "overlap", "segue_fade"} and self._on_mix_preview:
            self._preview_active = False  # oznacz nowy start
            logger.debug("Mix dialog: Alt+V mix preview via key=%s", active_key)
            ok = self._on_mix_preview(self._collect_mix_values())
            self._mix_preview_running = bool(ok)
            if not ok:
                wx.Bell()
            return
        self._mix_preview_running = False
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

    def _format_point_label(self, base: str, value: Optional[float]) -> str:
        if value is None:
            return base
        return f"{base} ({value:.3f}s)"

    def _update_point_label(self, key: str) -> None:
        row = self._rows[key]
        value = float(row.spin.GetValue()) if row.checkbox.GetValue() else None
        row.checkbox.SetLabel(self._format_point_label(row.base_label, value))

    def _handle_spin_edit(self, key: str) -> None:
        if key in {"overlap", "segue", "cue", "segue_fade"}:
            self._clamp_overlap_spin()
        self._update_point_label(key)
        if key in {"loop_start", "loop_end"}:
            self._ensure_loop_consistency()
        if key in {"segue", "segue_fade"}:
            row = self._rows.get(key)
            if row and row.checkbox.GetValue():
                self._preview_segue_window()

    def _current_cue_value(self) -> float:
        cue_row = self._rows.get("cue")
        if cue_row and cue_row.checkbox.GetValue():
            return float(cue_row.spin.GetValue())
        return self._cue_base

    def _current_segue_value(self) -> float:
        segue_row = self._rows.get("segue")
        if segue_row and segue_row.checkbox.GetValue():
            value = float(segue_row.spin.GetValue())
            cue_row = self._rows.get("cue")
            cue_base = cue_row.spin.GetValue() if cue_row and cue_row.checkbox.GetValue() else self._cue_base
            return max(0.0, value - (cue_base or 0.0))
        return 0.0

    def _max_allowed_overlap(self) -> float:
        cue_val = max(0.0, self._current_cue_value() or 0.0)
        segue_val = self._current_segue_value()
        return max(0.0, (self._duration or 0.0) - cue_val - max(0.0, segue_val))

    def _clamp_overlap_spin(self) -> None:
        overlap_row = self._rows.get("overlap")
        fade_row = self._rows.get("segue_fade")
        if overlap_row is None and fade_row is None:
            return
        max_overlap = self._max_allowed_overlap()
        upper = max_overlap if max_overlap > 0 else 0.0
        if overlap_row:
            overlap_row.spin.SetRange(0.0, upper)
            if overlap_row.checkbox.GetValue():
                value = float(overlap_row.spin.GetValue())
                if value > max_overlap:
                    overlap_row.spin.SetValue(max_overlap)
                    self._update_point_label("overlap")
        if fade_row:
            fade_row.spin.SetRange(0.0, upper)
            if fade_row.checkbox.GetValue():
                value = float(fade_row.spin.GetValue())
                if value > max_overlap:
                    fade_row.spin.SetValue(max_overlap)
                    self._update_point_label("segue_fade")

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

    def _set_row_enabled(self, row: "_MixPointRow", enabled: bool) -> None:
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
        if key in {"segue", "segue_fade"}:
            logger.debug("Mix dialog: preview_active_point key=%s", key)
            self._preview_segue_window(force=True)
            return
        value = float(row.spin.GetValue())
        start = value
        if row.mode == "duration":
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

    def _collect_mix_values(self) -> Dict[str, Optional[float]]:
        results: Dict[str, Optional[float]] = {}
        final_cue = None

        for key in ("cue", "intro", "outro", "segue", "segue_fade", "overlap"):
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

        return results
