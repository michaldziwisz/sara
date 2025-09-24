from pathlib import Path

import pytest

from sara.core.playlist import PlaylistItem, PlaylistModel
from sara.ui.undo import InsertOperation, MoveOperation, RemoveOperation


def _make_model(titles: list[str]) -> PlaylistModel:
    items = [
        PlaylistItem(
            id=f"id-{index}",
            path=Path(f"{title}.mp3"),
            title=title,
            duration_seconds=120.0,
        )
        for index, title in enumerate(titles)
    ]
    return PlaylistModel(id="pl-1", name="Test", items=items)


def test_insert_operation_apply_and_revert() -> None:
    model = _make_model(["A", "B"])
    new_items = [
        PlaylistItem(id="new-1", path=Path("X.mp3"), title="X", duration_seconds=100.0),
        PlaylistItem(id="new-2", path=Path("Y.mp3"), title="Y", duration_seconds=110.0),
    ]
    op = InsertOperation(indices=[1, 2], items=new_items)

    selection_after_apply = op.apply(model)
    assert [item.title for item in model.items] == ["A", "X", "Y", "B"]
    assert selection_after_apply == [1, 2]

    selection_after_revert = op.revert(model)
    assert [item.title for item in model.items] == ["A", "B"]
    assert selection_after_revert == [1]


def test_remove_operation_apply_and_revert() -> None:
    model = _make_model(["A", "B", "C"])
    items_to_remove = [model.items[1], model.items[2]]
    op = RemoveOperation(indices=[1, 2], items=list(items_to_remove))

    selection_after_apply = op.apply(model)
    assert [item.title for item in model.items] == ["A"]
    assert selection_after_apply == [0]

    selection_after_revert = op.revert(model)
    assert [item.title for item in model.items] == ["A", "B", "C"]
    assert selection_after_revert == [1, 2]


def test_move_operation_apply_and_revert() -> None:
    model = _make_model(["A", "B", "C", "D"]) 
    op = MoveOperation(original_indices=[1, 2], delta=1)

    selection_after_apply = op.apply(model)
    assert [item.title for item in model.items] == ["A", "D", "B", "C"]
    assert selection_after_apply == [2, 3]

    selection_after_revert = op.revert(model)
    assert [item.title for item in model.items] == ["A", "B", "C", "D"]
    assert selection_after_revert == [1, 2]


def test_move_operation_without_apply_raises_on_revert() -> None:
    model = _make_model(["A", "B"]) 
    op = MoveOperation(original_indices=[0], delta=1)
    with pytest.raises(ValueError):
        op.revert(model)
