"""Software audio mixer façade.

The implementation lives in smaller modules:
- `sara.audio.device_mixer`
- `sara.audio.mixer_player`
"""

from __future__ import annotations

from sara.audio.device_mixer import DeviceMixer, NullOutputStream
from sara.audio.mixer_player import MixerPlayer

__all__ = [
    "DeviceMixer",
    "MixerPlayer",
    "NullOutputStream",
]

