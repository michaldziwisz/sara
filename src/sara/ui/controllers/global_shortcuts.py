"""Compatibility wrapper for global shortcut helpers.

Implementation lives in `sara.ui.controllers.menu.global_shortcuts`.
"""

from __future__ import annotations

from sara.ui.controllers.menu.global_shortcuts import (
    handle_global_char_hook,
    handle_jingles_key,
    should_handle_altgr_track_remaining,
)

__all__ = [
    "handle_global_char_hook",
    "handle_jingles_key",
    "should_handle_altgr_track_remaining",
]
