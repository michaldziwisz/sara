"""Announcement categories used to control accessibility messages."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnnouncementCategory:
    id: str
    label: str
    default_enabled: bool = True


ANNOUNCEMENT_CATEGORIES: tuple[AnnouncementCategory, ...] = (
    AnnouncementCategory("general", "General status messages"),
    AnnouncementCategory("playlist", "Playlist management updates"),
    AnnouncementCategory("import_export", "Import and export messages"),
    AnnouncementCategory("playback_events", "Playback events"),
    AnnouncementCategory("playback_errors", "Playback errors"),
    AnnouncementCategory("loop", "Loop and intro notifications"),
    AnnouncementCategory("selection", "Selection notifications"),
    AnnouncementCategory("auto_mix", "Auto-mix announcements"),
    AnnouncementCategory("hotkeys", "Shortcut editor notifications"),
    AnnouncementCategory("clipboard", "Clipboard and move operations"),
    AnnouncementCategory("undo_redo", "Undo/redo notifications"),
    AnnouncementCategory("pfl", "PFL and preview warnings"),
    AnnouncementCategory("device", "Device availability warnings"),
    AnnouncementCategory("intro_alert", "Intro alert notifications"),
    AnnouncementCategory("track_end_alert", "Track end alert notifications"),
)

ANNOUNCEMENT_CATEGORY_MAP = {category.id: category for category in ANNOUNCEMENT_CATEGORIES}

__all__ = [
    "AnnouncementCategory",
    "ANNOUNCEMENT_CATEGORIES",
    "ANNOUNCEMENT_CATEGORY_MAP",
]
