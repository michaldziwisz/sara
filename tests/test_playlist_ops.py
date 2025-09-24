from pathlib import Path

import pytest

from sara.core.playlist import PlaylistItem
from sara.core.playlist_ops import move_items


def _make_items(names: list[str]) -> list[PlaylistItem]:
    items: list[PlaylistItem] = []
    for index, name in enumerate(names):
        items.append(
            PlaylistItem(
                id=f"id-{index}",
                path=Path(f"{name}.mp3"),
                title=name,
                duration_seconds=180.0,
            )
        )
    return items


def _titles(items: list[PlaylistItem]) -> list[str]:
    return [item.title for item in items]


def test_move_single_item_up() -> None:
    items = _make_items(["A", "B", "C"])
    new_indices = move_items(items, [1], -1)
    assert _titles(items) == ["B", "A", "C"]
    assert new_indices == [0]


def test_move_block_down() -> None:
    items = _make_items(["A", "B", "C", "D"])
    new_indices = move_items(items, [1, 2], 1)
    assert _titles(items) == ["A", "D", "B", "C"]
    assert new_indices == [2, 3]


def test_move_block_up_preserves_order() -> None:
    items = _make_items(["A", "B", "C", "D"])
    new_indices = move_items(items, [1, 3], -1)
    assert _titles(items) == ["B", "A", "D", "C"]
    assert new_indices == [0, 2]


def test_move_out_of_bounds_raises() -> None:
    items = _make_items(["A", "B"])
    with pytest.raises(ValueError):
        move_items(items, [0], -1)
    with pytest.raises(ValueError):
        move_items(items, [1], 1)


def test_empty_selection_raises() -> None:
    items = _make_items(["A", "B"])
    with pytest.raises(ValueError):
        move_items(items, [], 1)
