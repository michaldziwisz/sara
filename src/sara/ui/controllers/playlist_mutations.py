"""Playlist mutation helpers extracted from the main frame."""

from __future__ import annotations

from sara.core.playlist import PlaylistItem, PlaylistModel
from sara.ui.playlist_panel import PlaylistPanel


def remove_item_from_playlist(
    frame,
    panel: PlaylistPanel,
    model: PlaylistModel,
    index: int,
    *,
    refocus: bool = True,
) -> PlaylistItem:
    item = model.items.pop(index)
    if model.break_resume_index is not None:
        if index < model.break_resume_index:
            model.break_resume_index = max(0, model.break_resume_index - 1)
        elif index == model.break_resume_index and model.break_resume_index >= len(model.items):
            model.break_resume_index = None
    was_selected = item.is_selected
    item.is_selected = was_selected
    frame._forget_last_started_item(model.id, item.id)
    if any(key == (model.id, item.id) for key in frame._playback.contexts):
        frame._stop_playlist_playback(model.id, mark_played=False, fade_duration=0.0)
    if refocus:
        if model.items:
            next_index = min(index, len(model.items) - 1)
            frame._refresh_playlist_view(panel, [next_index])
        else:
            frame._refresh_playlist_view(panel, None)
    return item


def remove_items(
    frame,
    panel: PlaylistPanel,
    model: PlaylistModel,
    indices: list[int],
) -> list[PlaylistItem]:
    if not indices:
        return []
    removed: list[PlaylistItem] = []
    for index in sorted(indices, reverse=True):
        removed.append(remove_item_from_playlist(frame, panel, model, index, refocus=False))
    removed.reverse()
    if model.items:
        next_index = min(indices[0], len(model.items) - 1)
        frame._refresh_playlist_view(panel, [next_index])
    else:
        frame._refresh_playlist_view(panel, None)
    return removed

