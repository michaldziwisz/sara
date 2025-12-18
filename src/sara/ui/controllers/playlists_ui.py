"""Compatibility wrapper for playlist UI helpers.

Implementation lives in `sara.ui.controllers.playlists.ui`.
"""

from __future__ import annotations

from sara.ui.controllers.playlists.ui import (
    add_playlist,
    apply_playlist_order,
    create_ui,
    populate_startup_playlists,
    remove_playlist_by_id,
)

__all__ = [
    "add_playlist",
    "apply_playlist_order",
    "create_ui",
    "populate_startup_playlists",
    "remove_playlist_by_id",
]

