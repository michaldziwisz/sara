"""Compatibility wrapper for playlist focus helpers.

Implementation lives in `sara.ui.controllers.playlists.focus`.
"""

from __future__ import annotations

from sara.ui.controllers.playlists.focus import (
    ANNOUNCEMENT_PREFIX,
    active_news_panel,
    cycle_playlist_focus,
    focus_playlist_panel,
    focused_playlist_id,
    get_current_playlist_panel,
    handle_focus_click,
    maybe_focus_playing_item,
    on_playlist_focus,
    on_playlist_selection_change,
    on_toggle_selection,
    refresh_news_panels,
    update_active_playlist_styles,
)

__all__ = [
    "ANNOUNCEMENT_PREFIX",
    "active_news_panel",
    "cycle_playlist_focus",
    "focus_playlist_panel",
    "focused_playlist_id",
    "get_current_playlist_panel",
    "handle_focus_click",
    "maybe_focus_playing_item",
    "on_playlist_focus",
    "on_playlist_selection_change",
    "on_toggle_selection",
    "refresh_news_panels",
    "update_active_playlist_styles",
]

