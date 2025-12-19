"""Output device helpers for the software audio mixer."""

from __future__ import annotations

import logging
from typing import Optional

from sara.audio.mixer.types import NullOutputStream
from sara.audio.types import AudioDevice

logger = logging.getLogger(__name__)


def detect_device_format(
    *,
    sd,
    device: AudioDevice,
    default_samplerate: int = 48000,
    default_channels: int = 2,
    logger: Optional[logging.Logger] = None,
) -> tuple[int, int]:
    if logger is None:
        logger = logging.getLogger(__name__)

    samplerate = default_samplerate
    channels = default_channels
    if sd is None or device.raw_index is None:
        return samplerate, channels
    try:
        info = sd.query_devices(device.raw_index)
        samplerate = int(info.get("default_samplerate") or samplerate)
        channels = int(info.get("max_output_channels") or channels)
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Nie udało się pobrać parametrów urządzenia %s: %s", device.name, exc)
    channels = max(1, channels)
    return samplerate, channels


def default_stream_factory(
    *,
    sd,
    device: AudioDevice,
    block_size: int,
    samplerate: float,
    channels: int,
):
    if sd is None:
        return NullOutputStream(samplerate, channels)
    kwargs = {
        "device": device.raw_index,
        "samplerate": samplerate,
        "channels": channels,
        "dtype": "float32",
        "blocksize": block_size,
    }
    return sd.OutputStream(**kwargs)
