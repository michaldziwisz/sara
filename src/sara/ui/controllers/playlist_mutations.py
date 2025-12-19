"""Compatibility wrapper for playlist mutation helpers.

Implementation lives in `sara.ui.controllers.playlists.mutations`.
"""

from __future__ import annotations

from sara.ui.controllers.playlists.mutations import remove_item_from_playlist, remove_items

__all__ = [
    "remove_item_from_playlist",
    "remove_items",
]

