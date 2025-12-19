"""Dedicated undo/redo manager for playlist operations."""

from __future__ import annotations

from typing import Callable, List

from sara.ui.services.undo import UndoAction


class UndoManager:
    """Stores undo/redo stacks and executes actions."""

    def __init__(self, apply_callback: Callable[[UndoAction, bool], bool]) -> None:
        self._undo_stack: List[UndoAction] = []
        self._redo_stack: List[UndoAction] = []
        self._apply_callback = apply_callback

    def push(self, action: UndoAction) -> None:
        self._undo_stack.append(action)
        self._redo_stack.clear()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        action = self._undo_stack.pop()
        if self._apply_callback(action, True):
            self._redo_stack.append(action)
            return True
        self._redo_stack.clear()
        return False

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        action = self._redo_stack.pop()
        if self._apply_callback(action, False):
            self._undo_stack.append(action)
            return True
        self._undo_stack.clear()
        return False

    def clear(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()


__all__ = [
    "UndoManager",
]

