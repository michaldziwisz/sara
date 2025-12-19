"""Playlist item type editing actions (song/spot)."""

from __future__ import annotations

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItemType, PlaylistKind


def _selected_or_focused_indices(panel) -> list[int]:
    indices = list(panel.get_selected_indices() or [])
    if indices:
        return indices
    focused = panel.get_focused_index()
    if focused is None:
        return []
    try:
        focused_int = int(focused)
    except (TypeError, ValueError):
        return []
    return [] if focused_int < 0 else [focused_int]


def apply_item_type_to_selection(frame, item_type: PlaylistItemType) -> None:
    panel = frame._get_audio_panel((PlaylistKind.MUSIC, PlaylistKind.FOLDER))
    if panel is None:
        frame._announce_event("playlist", _("Select a playlist first"))
        return

    model = panel.model
    indices = _selected_or_focused_indices(panel)
    if not indices:
        if not model.items:
            frame._announce_event("playlist", _("Playlist is empty"))
            return
        indices = [0]
        panel.set_selection(indices, focus=True)

    changed = 0
    unique_indices = sorted(set(indices))
    for index in unique_indices:
        if 0 <= index < len(model.items):
            item = model.items[index]
            if item.item_type is not item_type:
                item.item_type = item_type
                changed += 1

    panel.refresh(indices, focus=True)

    label = _("song") if item_type is PlaylistItemType.SONG else _("spot")
    noun = _("track") if changed == 1 else _("tracks")
    if changed:
        frame._announce_event("playlist", _("Marked %d %s as %s") % (changed, noun, label))
    else:
        frame._announce_event("playlist", _("Track type already set to %s") % label)


def on_mark_as_song(frame, _event) -> None:
    apply_item_type_to_selection(frame, PlaylistItemType.SONG)


def on_mark_as_spot(frame, _event) -> None:
    apply_item_type_to_selection(frame, PlaylistItemType.SPOT)

