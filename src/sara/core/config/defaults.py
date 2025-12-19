"""Default configuration values."""

from __future__ import annotations

from typing import Any, Dict

from sara.core.announcement_registry import ANNOUNCEMENT_CATEGORIES
from sara.core.shortcuts import ensure_defaults

DEFAULT_CONFIG: Dict[str, Any] = {
    "general": {
        "language": "en",
    },
    "news": {
        "line_length": 30,
    },
    "shortcuts": {
        "global": {
            "play_next": "SPACE",
            "auto_mix_toggle": "CTRL+SHIFT+M",
            "loop_playback_toggle": "CTRL+SHIFT+L",
            "loop_info": "CTRL+ALT+SHIFT+L",
            "track_remaining": "CTRL+ALT+T",
        },
        "playlist_menu": {
            "new": "CTRL+N",
            "add_tracks": "CTRL+D",
            "assign_device": "CTRL+SHIFT+D",
            "import": "CTRL+O",
            "remove": "CTRL+DELETE",
            "manage": "CTRL+SHIFT+DELETE",
            "export": "CTRL+S",
            "exit": "ALT+F4",
        },
        "playlist": {
            "play": "F1",
            "pause": "F2",
            "stop": "F3",
            "fade": "F4",
            "break_toggle": "CTRL+B",
            "mix_points": "CTRL+P",
        },
        "edit": {
            "undo": "CTRL+Z",
            "redo": "CTRL+SHIFT+Z",
            "cut": "CTRL+X",
            "copy": "CTRL+C",
            "paste": "CTRL+V",
            "delete": "DELETE",
            "move_up": "ALT+UP",
            "move_down": "ALT+DOWN",
        },
    },
    "playback": {
        "fade_out_seconds": 0.0,
        "alternate_play_next": False,
        "auto_remove_played": False,
        "intro_alert_seconds": 5.0,
        "track_end_alert_seconds": 10.0,
        "swap_play_select": False,
    },
    "startup": {
        "playlists": [],
    },
    "devices": {
        "playlists": {},
        "pfl": None,
        "jingles": None,
    },
    "accessibility": {
        "announcements": {},
        "follow_playing_selection": True,
    },
    "diagnostics": {
        "faulthandler": False,
        "faulthandler_interval": 40.0,
        "loop_debug": False,
        "log_level": "WARNING",
    },
    "logging": {
        "enabled": False,
        "songs": True,
        "spots": True,
        "folder": "",
    },
    "now_playing": {
        "enabled": False,
        "path": "",
        "update_on_track_change": True,
        "update_interval_seconds": 0,
        "template": "%artist - %title",
        "songs": True,
        "spots": True,
    },
}

DEFAULT_ANNOUNCEMENTS = {
    category.id: category.default_enabled for category in ANNOUNCEMENT_CATEGORIES
}

ensure_defaults(DEFAULT_CONFIG["shortcuts"])
