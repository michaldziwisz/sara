"""Playlist selection context helpers."""

from __future__ import annotations

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistKind, PlaylistModel
from sara.ui.playlist_panel import PlaylistPanel


def get_selected_context(
    frame,
    *,
    kinds: tuple[PlaylistKind, ...] = (PlaylistKind.MUSIC,),
) -> tuple[PlaylistPanel, PlaylistModel, list[int]] | None:
    panel = frame._get_audio_panel(kinds)
    if panel is None:
        frame._announce_event("playlist", _("Select a playlist first"))
        return None
    indices = panel.get_selected_indices()
    if not indices:
        if panel.model.items:
            indices = [0]
            panel.set_selection(indices)
        else:
            frame._announce_event("playlist", _("Playlist is empty"))
            return None
    return panel, panel.model, sorted(indices)


def get_selected_items(
    frame,
    *,
    kinds: tuple[PlaylistKind, ...] = (PlaylistKind.MUSIC,),
) -> tuple[PlaylistPanel, PlaylistModel, list[tuple[int, PlaylistItem]]] | None:
    context = get_selected_context(frame, kinds=kinds)
    if context is None:
        return None
    panel, model, indices = context
    selected: list[tuple[int, PlaylistItem]] = []
    for index in indices:
        if 0 <= index < len(model.items):
            selected.append((index, model.items[index]))
    if not selected:
        frame._announce_event("playlist", _("No tracks selected"))
        return None
    return panel, model, selected
