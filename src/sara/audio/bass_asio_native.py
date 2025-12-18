"""Compatibility façade for BASS ASIO native bindings.

The implementation lives in `sara.audio.bass.asio_native`.
"""

from __future__ import annotations

from sara.audio.bass.asio_native import _BassAsioLibrary, _BASS_ASIO_DEVICEINFO

__all__ = [
    "_BassAsioLibrary",
    "_BASS_ASIO_DEVICEINFO",
]

