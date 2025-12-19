"""Playlist panel refresh helpers for playback flow."""

from __future__ import annotations

import wx

from sara.ui.playlist_panel import PlaylistPanel


def capture_panel_selection(panel: PlaylistPanel) -> tuple[list[int], int]:
    return panel.get_selected_indices(), panel.get_focused_index()


def refresh_preserving_selection(
    panel: PlaylistPanel,
    *,
    previous_selection: list[int],
    previous_focus: int,
    item_count: int,
) -> None:
    if previous_selection:
        panel.refresh(selected_indices=previous_selection, focus=True)
        return
    if previous_focus != wx.NOT_FOUND and 0 <= previous_focus < item_count:
        panel.refresh(focus=False)
        panel.select_index(previous_focus, focus=True)
        return
    panel.refresh(focus=False)

