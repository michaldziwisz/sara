"""Sounddevice player profiles and device matching."""

from __future__ import annotations

import logging
from typing import Optional

import sara.audio.sounddevice_player_base as base
from sara.audio.types import AudioDevice

logger = logging.getLogger(__name__)


def _match_sounddevice_device(target_name: str, host_keywords: tuple[str, ...]) -> Optional[int]:
    sd = base.sd
    if sd is None:
        return None
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Nie udało się pobrać listy urządzeń sounddevice: %s", exc)
        return None

    target_lower = target_name.lower()
    exact_matches: list[tuple[int, int]] = []
    partial_matches: list[tuple[int, int]] = []

    for index, info in enumerate(devices):
        host_name = hostapis[info["hostapi"]]["name"]
        keyword_index = next(
            (i for i, keyword in enumerate(host_keywords) if keyword.lower() in host_name.lower()),
            None,
        )
        if keyword_index is None:
            continue
        if info.get("max_output_channels", 0) <= 0:
            continue
        name_lower = info["name"].lower()
        entry = (keyword_index, index)
        if name_lower == target_lower:
            exact_matches.append(entry)
        elif target_lower in name_lower:
            partial_matches.append(entry)

    if exact_matches:
        _, chosen = min(exact_matches, key=lambda pair: (pair[0], pair[1]))
        return chosen
    if partial_matches:
        _, chosen = min(partial_matches, key=lambda pair: (pair[0], pair[1]))
        return chosen
    return None


class WasapiPlayer(base.SoundDevicePlayer):
    """Player wykorzystujący urządzenie WASAPI poprzez sounddevice."""

    def __init__(self, device: AudioDevice):
        if device.raw_index is None:
            raw_index = _match_sounddevice_device(device.name, ("WASAPI", "MME"))
            if raw_index is None:
                raise RuntimeError("Nie znaleziono odpowiednika WASAPI w sounddevice")
            device.raw_index = raw_index
        super().__init__(device, stream_kwargs={"blocksize": 512, "latency": "low"})


class AsioPlayer(base.SoundDevicePlayer):
    """Player wykorzystujący sterownik ASIO (przez sounddevice)."""

    def __init__(self, device: AudioDevice):
        if device.raw_index is None:
            raw_index = _match_sounddevice_device(device.name, ("ASIO",))
            if raw_index is None:
                raise RuntimeError("Nie znaleziono odpowiednika ASIO w sounddevice")
            device.raw_index = raw_index
        super().__init__(device, stream_kwargs={"blocksize": 256, "latency": "low"})


__all__ = [
    "AsioPlayer",
    "WasapiPlayer",
]

