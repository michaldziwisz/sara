from __future__ import annotations

from dataclasses import dataclass

from sara.ui.undo_manager import UndoManager
from sara.ui.undo import UndoAction


@dataclass
class DummyOperation:
    value: int = 0


def test_undo_manager_executes_and_tracks_redo():
    executed = []

    def apply(action, reverse):
        executed.append((action.playlist_id, reverse))
        return True

    manager = UndoManager(apply)
    manager.push(UndoAction("pl-1", DummyOperation()))
    assert manager.undo() is True
    assert executed == [("pl-1", True)]
    assert manager.redo() is True
    assert executed[-1] == ("pl-1", False)
