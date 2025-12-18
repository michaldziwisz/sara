"""Line length configuration helpers for `NewsPlaylistPanel`."""

from __future__ import annotations

import wx


def normalize_line_length(panel, value: int) -> int:
    minimum, maximum = panel._line_length_bounds
    normalized = max(minimum, value)
    if maximum > minimum:
        normalized = min(normalized, maximum)
    return normalized


def sync_line_length_spin(panel) -> None:
    if panel._line_length_spin:
        panel._line_length_spin.SetValue(normalize_line_length(panel, panel._get_line_length()))


def handle_line_length_change(panel, _event: wx.Event | None) -> None:
    if not panel._line_length_spin or not panel._on_line_length_change:
        return
    value = normalize_line_length(panel, panel._line_length_spin.GetValue())
    panel._line_length_spin.SetValue(value)
    panel._on_line_length_change(value)
    panel.refresh_configuration()


def handle_line_apply(panel, _event: wx.Event) -> None:
    handle_line_length_change(panel, None)
    if panel._on_line_length_apply:
        panel._on_line_length_apply()

