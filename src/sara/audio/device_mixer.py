"""Device mixer façade.

The implementation lives in `sara.audio.mixer.device_mixer`.
"""

from __future__ import annotations

from sara.audio.mixer.device_mixer import DeviceMixer
from sara.audio.mixer.types import NullOutputStream

__all__ = [
    "DeviceMixer",
    "NullOutputStream",
]

