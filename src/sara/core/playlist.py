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


class PlaylistKind(Enum):
    MUSIC = "music"
    NEWS = "news"


@dataclass
class PlaylistItem:
    id: str
    path: Path
    title: str
    duration_seconds: float
    artist: Optional[str] = None
    status: PlaylistItemStatus = PlaylistItemStatus.PENDING
    current_position: float = 0.0
    replay_gain_db: Optional[float] = None
    cue_in_seconds: Optional[float] = None
    segue_seconds: Optional[float] = None
    overlap_seconds: Optional[float] = None
    intro_seconds: Optional[float] = None
    outro_seconds: Optional[float] = None
    loop_start_seconds: Optional[float] = None
    loop_end_seconds: Optional[float] = None
    loop_auto_enabled: bool = False
    loop_enabled: bool = False
    break_after: bool = False
    is_selected: bool = False

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
        self.loop_auto_enabled = False
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
    kind: PlaylistKind = PlaylistKind.MUSIC
    output_slots: List[Optional[str]] = field(default_factory=list)
    next_slot_index: int = 0
    items: List[PlaylistItem] = field(default_factory=list)
    hotkeys: Dict[str, "HotkeyAction"] = field(default_factory=dict)
    break_resume_index: Optional[int] = None

    # backward compatibility: single device
    output_device: Optional[str] = None
    news_markdown: str = ""

    def next_item(self) -> Optional[PlaylistItem]:
        for item in self.items:
            if item.status is PlaylistItemStatus.PENDING:
                return item
        return None

    def begin_next_item(self, preferred_item_id: Optional[str] = None) -> Optional[PlaylistItem]:
        if preferred_item_id:
            preferred = self.get_item(preferred_item_id)
            if preferred:
                if preferred.status is PlaylistItemStatus.PAUSED:
                    preferred.status = PlaylistItemStatus.PLAYING
                    return preferred
                if preferred.status is PlaylistItemStatus.PLAYING:
                    return preferred
                if preferred.status is PlaylistItemStatus.PLAYED:
                    preferred.current_position = 0.0
                    preferred.status = PlaylistItemStatus.PENDING
                if preferred.status is not PlaylistItemStatus.PENDING:
                    preferred.current_position = 0.0
                    preferred.status = PlaylistItemStatus.PENDING
                preferred.status = PlaylistItemStatus.PLAYING
                if preferred.current_position <= 0.0:
                    preferred.current_position = 0.0
                return preferred

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

    def toggle_selection(self, item_id: str) -> bool:
        for item in self.items:
            if item.id == item_id:
                item.is_selected = not item.is_selected
                if item.is_selected and item.status is not PlaylistItemStatus.PENDING:
                    item.status = PlaylistItemStatus.PENDING
                    item.current_position = 0.0
                return item.is_selected
        return False

    def clear_selection(self, item_id: Optional[str] = None) -> None:
        if item_id is None:
            for item in self.items:
                item.is_selected = False
            return
        for item in self.items:
            if item.id == item_id:
                item.is_selected = False
                break

    def next_selected_item_id(self) -> Optional[str]:
        for item in self.items:
            if item.is_selected and item.status in (PlaylistItemStatus.PENDING, PlaylistItemStatus.PAUSED):
                return item.id
        return None

    def has_selected_items(self) -> bool:
        return any(item.is_selected for item in self.items)

    def reset_progress(self, item_id: str) -> None:
        for item in self.items:
            if item.id == item_id:
                item.current_position = 0.0
                if item.status is PlaylistItemStatus.PLAYING:
                    item.status = PlaylistItemStatus.PENDING
                break

    def reset_from(self, item_id: str) -> None:
        reset = False
        for item in self.items:
            if item.id == item_id:
                reset = True
            if reset:
                item.current_position = 0.0
                if item.status is not PlaylistItemStatus.PENDING:
                    item.status = PlaylistItemStatus.PENDING


# Future integration: import to avoid circular dependency
from sara.core.hotkeys import HotkeyAction  # noqa: E402  # pylint: disable=wrong-import-position
