"""Compatibility façade for BASS native bindings.

The implementation lives in `sara.audio.bass.native`.
"""

from __future__ import annotations

from sara.audio.bass.native import BassNotAvailable, _BassConstants, _BASS_DEVICEINFO, _BassLibrary

__all__ = [
    "BassNotAvailable",
    "_BassConstants",
    "_BASS_DEVICEINFO",
    "_BassLibrary",
]

