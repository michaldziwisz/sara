"""Logic for ordering playlists and tracking focus separate from wx UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


@dataclass
class PlaylistLayoutState:
    order: List[str] = field(default_factory=list)
    current_id: Optional[str] = None
    focus_lock: Dict[str, bool] = field(default_factory=dict)


class PlaylistLayoutManager:
    """Tracks playlist order and selection independent from actual wx controls."""

    def __init__(self, state: PlaylistLayoutState | None = None) -> None:
        self.state = state or PlaylistLayoutState()

    def add_playlist(self, playlist_id: str) -> None:
        if playlist_id not in self.state.order:
            self.state.order.append(playlist_id)
        if self.state.current_id is None:
            self.state.current_id = playlist_id

    def remove_playlist(self, playlist_id: str) -> None:
        self.state.order = [pid for pid in self.state.order if pid != playlist_id]
        self.state.focus_lock.pop(playlist_id, None)
        if self.state.current_id == playlist_id:
            self.state.current_id = self.state.order[0] if self.state.order else None

    def apply_order(self, requested_order: Iterable[str]) -> List[str]:
        filtered = [pid for pid in requested_order if pid in self.state.order]
        remaining = [pid for pid in self.state.order if pid not in filtered]
        self.state.order = filtered + remaining
        if self.state.current_id not in self.state.order:
            self.state.current_id = self.state.order[0] if self.state.order else None
        return list(self.state.order)

    def set_current(self, playlist_id: str | None) -> None:
        if playlist_id in self.state.order:
            self.state.current_id = playlist_id

    def current_index(self) -> int:
        if self.state.current_id and self.state.current_id in self.state.order:
            return self.state.order.index(self.state.current_id)
        return 0

    def cycle(self, *, backwards: bool = False) -> str | None:
        if not self.state.order:
            return None
        index = self.current_index()
        if backwards:
            index = (index - 1) % len(self.state.order)
        else:
            index = (index + 1) % len(self.state.order)
        self.state.current_id = self.state.order[index]
        return self.state.current_id


__all__ = [
    "PlaylistLayoutManager",
    "PlaylistLayoutState",
]

