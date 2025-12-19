"""Lightweight automix cursor tracking independent of UI focus/selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from sara.core.playlist import PlaylistModel


@dataclass
class AutoMixTracker:
    """Maintains a virtual cursor per playlist for automix sequencing."""

    _last_item_id: Dict[str, Optional[str]] = field(default_factory=dict)
    _last_started_pending: Dict[str, Optional[str]] = field(default_factory=dict)

    def drop_playlist(self, playlist_id: str) -> None:
        self._last_item_id.pop(playlist_id, None)

    def set_last_started(self, playlist_id: str, item_id: Optional[str]) -> None:
        self._last_item_id[playlist_id] = item_id
        self._last_started_pending.pop(playlist_id, None)

    def stage_next(self, playlist_id: str, item_id: str) -> None:
        """Remember which item is about to start; committed on set_last_started."""
        self._last_started_pending[playlist_id] = item_id

    def reset_if_empty(self, model: PlaylistModel) -> None:
        if not model.items:
            self.drop_playlist(model.id)

    def _index_of_last(self, model: PlaylistModel) -> Optional[int]:
        last_id = self._last_started_pending.get(model.id) or self._last_item_id.get(model.id)
        if not last_id:
            return None
        for idx, entry in enumerate(model.items):
            if entry.id == last_id:
                return idx
        return None

    def next_index(self, model: PlaylistModel, *, break_resume_index: Optional[int] = None) -> int:
        """Return sequential index for automix. Ignores UI focus/selection."""
        total = len(model.items)
        if total == 0:
            return 0
        if break_resume_index is not None:
            return break_resume_index % total
        last_idx = self._index_of_last(model)
        if last_idx is None:
            return 0
        return (last_idx + 1) % total


__all__ = [
    "AutoMixTracker",
]

