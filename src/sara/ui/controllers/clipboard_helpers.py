"""Compatibility wrapper for clipboard helpers.

Implementation lives in `sara.ui.controllers.playlists.clipboard`.
"""

from __future__ import annotations

from sara.ui.controllers.playlists.clipboard import (
    create_item_from_serialized,
    get_system_clipboard_paths,
    serialize_items,
    set_system_clipboard_paths,
)

__all__ = [
    "create_item_from_serialized",
    "get_system_clipboard_paths",
    "serialize_items",
    "set_system_clipboard_paths",
]

