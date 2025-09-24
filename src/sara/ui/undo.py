"""Undo/redo support structures for playlist edits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol

from sara.core.playlist import PlaylistItem, PlaylistModel
from sara.core.playlist_ops import move_items


class PlaylistOperation(Protocol):
    def apply(self, model: PlaylistModel) -> List[int]:
        """Apply the change to the playlist and return selected indices."""

    def revert(self, model: PlaylistModel) -> List[int]:
        """Undo the change and return selected indices."""


@dataclass
class UndoAction:
    playlist_id: str
    operation: PlaylistOperation

    def apply(self, model: PlaylistModel) -> List[int]:
        return self.operation.apply(model)

    def revert(self, model: PlaylistModel) -> List[int]:
        return self.operation.revert(model)


@dataclass
class InsertOperation:
    indices: List[int]
    items: List[PlaylistItem]

    def apply(self, model: PlaylistModel) -> List[int]:
        for index, item in sorted(zip(self.indices, self.items), key=lambda pair: pair[0]):
            model.items.insert(index, item)
        return list(self.indices)

    def revert(self, model: PlaylistModel) -> List[int]:
        for index in sorted(self.indices, reverse=True):
            model.items.pop(index)
        if not model.items:
            return []
        anchor = min(self.indices)
        anchor = min(anchor, len(model.items) - 1)
        return [anchor] if anchor >= 0 else []


@dataclass
class RemoveOperation:
    indices: List[int]
    items: List[PlaylistItem]

    def apply(self, model: PlaylistModel) -> List[int]:
        removed: List[PlaylistItem] = []
        for index in sorted(self.indices, reverse=True):
            removed.append(model.items.pop(index))
        removed.reverse()
        assert removed == self.items
        if not model.items:
            return []
        anchor = min(self.indices)
        anchor = min(anchor, len(model.items) - 1)
        return [anchor] if anchor >= 0 else []

    def revert(self, model: PlaylistModel) -> List[int]:
        for index, item in sorted(zip(self.indices, self.items), key=lambda pair: pair[0]):
            model.items.insert(index, item)
        return list(self.indices)


@dataclass
class MoveOperation:
    original_indices: List[int]
    delta: int
    _last_new_indices: List[int] | None = None

    def apply(self, model: PlaylistModel) -> List[int]:
        new_indices = move_items(model.items, self.original_indices, self.delta)
        self._last_new_indices = new_indices
        return new_indices

    def revert(self, model: PlaylistModel) -> List[int]:
        if self._last_new_indices is None:
            raise ValueError("MoveOperation not previously applied")
        original = move_items(model.items, self._last_new_indices, -self.delta)
        self._last_new_indices = None
        return original
