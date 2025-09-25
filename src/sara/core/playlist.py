"""Playlist data models and logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional


class PlaylistItemStatus(Enum):
    PENDING = "Scheduled"
    PLAYING = "Playing"
    PAUSED = "Paused"
    PLAYED = "Played"


@dataclass
class PlaylistItem:
    id: str
    path: Path
    title: str
    duration_seconds: float
    status: PlaylistItemStatus = PlaylistItemStatus.PENDING
    current_position: float = 0.0
    replay_gain_db: Optional[float] = None
    cue_in_seconds: Optional[float] = None
    segue_seconds: Optional[float] = None
    overlap_seconds: Optional[float] = None
    intro_seconds: Optional[float] = None
    loop_start_seconds: Optional[float] = None
    loop_end_seconds: Optional[float] = None
    loop_enabled: bool = False
    is_marker: bool = False

    @property
    def duration_display(self) -> str:
        minutes, seconds = divmod(int(self.effective_duration_seconds), 60)
        return f"{minutes:02d}:{seconds:02d}"

    @property
    def progress_display(self) -> str:
        played_minutes, played_seconds = divmod(int(self.current_position), 60)
        total_minutes, total_seconds = divmod(int(self.effective_duration_seconds), 60)
        total_text = f"{total_minutes:02d}:{total_seconds:02d}" if self.duration_seconds else "--:--"
        return f"{played_minutes:02d}:{played_seconds:02d} / {total_text}"

    def update_progress(self, seconds: float) -> None:
        effective = seconds - (self.cue_in_seconds or 0.0)
        effective = max(0.0, effective)
        effective = min(effective, self.effective_duration_seconds)
        self.current_position = effective
        if self.status is PlaylistItemStatus.PENDING and self.current_position > 0:
            self.status = PlaylistItemStatus.PLAYING

    @property
    def effective_duration_seconds(self) -> float:
        cue = self.cue_in_seconds or 0.0
        return max(0.0, self.duration_seconds - cue)

    def set_loop(self, start_seconds: float, end_seconds: float) -> None:
        if start_seconds < 0 or end_seconds <= start_seconds:
            raise ValueError("Invalid loop values")
        self.loop_start_seconds = start_seconds
        self.loop_end_seconds = end_seconds

    def clear_loop(self) -> None:
        self.loop_start_seconds = None
        self.loop_end_seconds = None
        self.loop_enabled = False

    def has_loop(self) -> bool:
        return (
            self.loop_start_seconds is not None
            and self.loop_end_seconds is not None
            and self.loop_end_seconds > self.loop_start_seconds
        )


@dataclass
class PlaylistModel:
    id: str
    name: str
    output_slots: List[Optional[str]] = field(default_factory=list)
    next_slot_index: int = 0
    items: List[PlaylistItem] = field(default_factory=list)
    hotkeys: Dict[str, "HotkeyAction"] = field(default_factory=dict)

    # backward compatibility: single device
    output_device: Optional[str] = None

    def next_item(self) -> Optional[PlaylistItem]:
        for item in self.items:
            if item.status is PlaylistItemStatus.PENDING:
                return item
        return None

    def begin_next_item(self, marker_item_id: Optional[str] = None) -> Optional[PlaylistItem]:
        if marker_item_id:
            marker = self.get_item(marker_item_id)
            if marker:
                if marker.status is PlaylistItemStatus.PAUSED:
                    marker.status = PlaylistItemStatus.PLAYING
                    return marker
                if marker.status is PlaylistItemStatus.PENDING:
                    marker.status = PlaylistItemStatus.PLAYING
                    if marker.current_position <= 0.0:
                        marker.current_position = 0.0
                    return marker
                if marker.status is PlaylistItemStatus.PLAYED:
                    marker.current_position = 0.0
                    marker.status = PlaylistItemStatus.PLAYING
                    return marker
                if marker.status is PlaylistItemStatus.PLAYING:
                    return marker

        paused = next((item for item in self.items if item.status is PlaylistItemStatus.PAUSED), None)
        if paused:
            paused.status = PlaylistItemStatus.PLAYING
            return paused

        item = self.next_item()
        if item:
            item.status = PlaylistItemStatus.PLAYING
            if item.current_position <= 0.0:
                item.current_position = 0.0
        return item

    def mark_played(self, item_id: str) -> None:
        for item in self.items:
            if item.id == item_id:
                item.status = PlaylistItemStatus.PLAYED
                item.current_position = item.effective_duration_seconds
                break

    def add_items(self, new_items: Iterable[PlaylistItem]) -> None:
        self.items.extend(new_items)

    def set_output_slots(self, slots: Iterable[Optional[str]]) -> None:
        self.output_slots = list(slots)
        self.output_device = None
        self.next_slot_index = 0

    def get_configured_slots(self) -> List[Optional[str]]:
        if self.output_slots:
            return self.output_slots
        if self.output_device:
            return [self.output_device]
        return []

    def select_next_slot(self, available_devices: set[str], busy_devices: set[str]) -> Optional[tuple[int, str]]:
        slots = self.get_configured_slots()
        fallback = False
        if not slots and available_devices:
            slots = sorted(available_devices)
            fallback = True
        if not slots:
            return None

        count = len(slots)
        if count == 0:
            return None

        start_index = self.next_slot_index % count

        for phase in ("free", "available"):
            for offset in range(count):
                idx = (start_index + offset) % count
                device_id = slots[idx]
                if not device_id:
                    continue
                if device_id not in available_devices:
                    continue
                if phase == "free" and device_id in busy_devices:
                    continue
                self.next_slot_index = (idx + 1) % count
                return idx if not fallback else idx % max(count, 1), device_id

        return None

    def remove_item(self, item_id: str) -> None:
        self.items = [item for item in self.items if item.id != item_id]

    def get_item(self, item_id: str) -> Optional[PlaylistItem]:
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def set_marker(self, item_id: Optional[str]) -> None:
        for item in self.items:
            item.is_marker = item.id == item_id if item_id else False

    def reset_progress(self, item_id: str) -> None:
        for item in self.items:
            if item.id == item_id:
                item.current_position = 0.0
                if item.status is PlaylistItemStatus.PLAYING:
                    item.status = PlaylistItemStatus.PENDING
                break


# Future integration: import to avoid circular dependency
from sara.core.hotkeys import HotkeyAction  # noqa: E402  # pylint: disable=wrong-import-position
