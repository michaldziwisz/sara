"""BASS player implementation.

The implementation lives in `sara.audio.bass.player.base`.
"""

from __future__ import annotations

from sara.audio.bass.player.base import (
    BassPlayer,
    _DEBUG_LOOP,
    _LOOP_GUARD_BASE_SLACK,
    _LOOP_GUARD_FALLBACK_SLACK,
)

__all__ = [
    "BassPlayer",
    "_DEBUG_LOOP",
    "_LOOP_GUARD_BASE_SLACK",
    "_LOOP_GUARD_FALLBACK_SLACK",
]
