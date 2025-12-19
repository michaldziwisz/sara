"""Sounddevice player core façade.

The implementation lives in `sara.audio.sounddevice.player_base`.
"""

from __future__ import annotations

from sara.audio.sounddevice.player_base import SoundDevicePlayer, np, sd, sf

__all__ = [
    "SoundDevicePlayer",
    "np",
    "sd",
    "sf",
]

