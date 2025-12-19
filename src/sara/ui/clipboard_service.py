"""Compatibility wrapper for playlist clipboard helper.

Implementation lives in `sara.ui.services.clipboard_service`.
"""

from __future__ import annotations

from sara.ui.services.clipboard_service import ClipboardEntry, PlaylistClipboard

__all__ = [
    "ClipboardEntry",
    "PlaylistClipboard",
]
