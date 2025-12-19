"""Compatibility façade for BASS backend providers.

The implementation lives in `sara.audio.bass.backends`.
"""

from __future__ import annotations

from sara.audio.bass.backends import BassAsioBackend, BassBackend

__all__ = [
    "BassAsioBackend",
    "BassBackend",
]

