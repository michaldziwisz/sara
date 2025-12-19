"""Compatibility façade for `BassManager`.

The implementation lives in `sara.audio.bass.manager`.
"""

from __future__ import annotations

from sara.audio.bass.manager import BassManager, _AsioDeviceContext, _DeviceContext

__all__ = [
    "BassManager",
    "_AsioDeviceContext",
    "_DeviceContext",
]

