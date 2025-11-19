"""Clipboard helper for playlist operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Sequence


@dataclass
class ClipboardEntry:
    payload: Dict[str, Any]


class PlaylistClipboard:
    """Manages copy/paste payloads for playlists."""

    def __init__(self) -> None:
        self._entries: List[ClipboardEntry] = []

    def clear(self) -> None:
        self._entries.clear()

    def set(self, items: Sequence[Dict[str, Any]]) -> None:
        self._entries = [ClipboardEntry(payload=dict(item)) for item in items]

    def get(self) -> list[Dict[str, Any]]:
        return [entry.payload.copy() for entry in self._entries]

    def is_empty(self) -> bool:
        return not self._entries

