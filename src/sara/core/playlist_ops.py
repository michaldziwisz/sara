"""Helper operations for playlist item manipulation."""

from __future__ import annotations

from typing import List

from sara.core.playlist import PlaylistItem


def move_items(items: List[PlaylistItem], selected_indices: List[int], delta: int) -> List[int]:
    """Move selected items within a playlist by ``delta`` positions.

    Returns the new indices of the moved items in the same order as ``selected_indices``.
    Raises ``ValueError`` when the move would go out of bounds or the selection is empty.
    """

    if not selected_indices:
        raise ValueError("Selection required")
    if delta == 0:
        return list(selected_indices)

    count = len(items)
    unique_indices = sorted(set(selected_indices))
    if any(index < 0 or index >= count for index in unique_indices):
        raise ValueError("Indices out of range")

    step = 1 if delta > 0 else -1
    moves = abs(delta)
    current_indices = unique_indices[:]

    for _ in range(moves):
        if step < 0 and current_indices[0] + step < 0:
            raise ValueError("Cannot move beyond start")
        if step > 0 and current_indices[-1] + step >= count:
            raise ValueError("Cannot move beyond end")

        if step < 0:
            for index in current_indices:
                items[index + step], items[index] = items[index], items[index + step]
            current_indices = [index + step for index in current_indices]
        else:
            for index in reversed(current_indices):
                items[index + step], items[index] = items[index], items[index + step]
            current_indices = [index + step for index in current_indices]

    index_map = {original: new for original, new in zip(unique_indices, current_indices)}
    return [index_map[index] for index in selected_indices]
