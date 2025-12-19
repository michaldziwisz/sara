"""Compatibility wrapper for item loading helpers.

Implementation lives in `sara.ui.controllers.playlists.item_loading`.
"""

from __future__ import annotations

from sara.ui.controllers.playlists.item_loading import (
    build_playlist_item,
    collect_files_from_paths,
    create_items_from_m3u_entries,
    create_items_from_paths,
    load_items_from_sources,
    load_playlist_item,
    logger,
    metadata_worker_count,
    run_item_loader,
)

__all__ = [
    "build_playlist_item",
    "collect_files_from_paths",
    "create_items_from_m3u_entries",
    "create_items_from_paths",
    "load_items_from_sources",
    "load_playlist_item",
    "logger",
    "metadata_worker_count",
    "run_item_loader",
]

