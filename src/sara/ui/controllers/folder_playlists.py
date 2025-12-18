"""Compatibility wrapper for folder playlist actions.

Implementation lives in `sara.ui.controllers.playlists.folder`.
"""

from __future__ import annotations

from sara.ui.controllers.playlists.folder import (
    finalize_folder_load,
    handle_folder_preview,
    load_folder_items,
    load_folder_playlist,
    reload_folder_playlist,
    select_folder_for_playlist,
    send_folder_items_to_music,
    stop_preview,
    target_music_playlist,
)

__all__ = [
    "finalize_folder_load",
    "handle_folder_preview",
    "load_folder_items",
    "load_folder_playlist",
    "reload_folder_playlist",
    "select_folder_for_playlist",
    "send_folder_items_to_music",
    "stop_preview",
    "target_music_playlist",
]

