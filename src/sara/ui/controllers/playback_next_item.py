"""Compatibility wrapper for playback selection helpers.

Implementation lives in `sara.ui.controllers.playback.next_item`.
"""

from __future__ import annotations

from sara.ui.controllers.playback.next_item import NextItemDecision, decide_next_item

__all__ = [
    "NextItemDecision",
    "decide_next_item",
]

