from __future__ import annotations

from pathlib import Path
from typing import Iterable

from sara.core.playlist import PlaylistItem, PlaylistModel


_MIX_POINT_ATTRS: tuple[tuple[str, str], ...] = (
    ("cue_in", "cue_in_seconds"),
    ("intro", "intro_seconds"),
    ("outro", "outro_seconds"),
    ("segue", "segue_seconds"),
    ("segue_fade", "segue_fade_seconds"),
    ("overlap", "overlap_seconds"),
)


def apply_mix_values(item: PlaylistItem, mix_values: dict[str, float | None]) -> bool:
    changed = False
    for key, attr in _MIX_POINT_ATTRS:
        new_val = mix_values.get(key)
        if getattr(item, attr) != new_val:
            setattr(item, attr, new_val)
            changed = True
    return changed


def propagate_mix_points_for_path(
    playlists: Iterable[PlaylistModel],
    *,
    path: Path,
    mix_values: dict[str, float | None],
    source_playlist_id: str,
    source_item_id: str,
) -> dict[str, list[str]]:
    """Update mix points for all items pointing to the same path.

    Returns a mapping {playlist_id: [item_id, ...]} for items that were updated.
    """
    updated: dict[str, list[str]] = {}
    for playlist in playlists:
        changed_ids: list[str] = []
        for item in playlist.items:
            if item.path != path:
                continue
            if playlist.id == source_playlist_id and item.id == source_item_id:
                continue
            if apply_mix_values(item, mix_values):
                changed_ids.append(item.id)
        if changed_ids:
            updated[playlist.id] = changed_ids
    return updated

