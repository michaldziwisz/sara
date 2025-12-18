"""Sounddevice player façade.

The concrete implementation lives in `sara.audio.sounddevice`.
This module exists to keep imports stable for the rest of the application.
"""

from __future__ import annotations

from sara.audio.sounddevice.player_base import SoundDevicePlayer, np, sd, sf
from sara.audio.sounddevice.profiles import AsioPlayer, WasapiPlayer

__all__ = [
    "AsioPlayer",
    "SoundDevicePlayer",
    "WasapiPlayer",
    "np",
    "sd",
    "sf",
]
