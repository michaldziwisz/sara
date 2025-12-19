"""Compatibility wrapper for playlist management actions.

Implementation lives in `sara.ui.controllers.playlists.management`.
"""

from __future__ import annotations

from sara.ui.controllers.playlists.management import (
    configure_playlist_devices,
    finalize_add_tracks,
    on_add_tracks,
    on_assign_device,
    on_manage_playlists,
    on_remove_playlist,
    prompt_new_playlist,
)

__all__ = [
    "configure_playlist_devices",
    "finalize_add_tracks",
    "on_add_tracks",
    "on_assign_device",
    "on_manage_playlists",
    "on_remove_playlist",
    "prompt_new_playlist",
]

