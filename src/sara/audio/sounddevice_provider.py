"""Sounddevice device enumeration and player factory."""

from __future__ import annotations

import logging
from typing import List

from sara.audio.mock_backend import MockPlayer
from sara.audio.sounddevice_player import SoundDevicePlayer, sd
from sara.audio.types import AudioDevice, BackendType, Player

logger = logging.getLogger(__name__)


class SoundDeviceBackend:
    """Backend oparty na bibliotece sounddevice (PortAudio)."""

    def __init__(self, backend: BackendType, keywords: tuple[str, ...]):
        self.backend = backend
        self._keywords = keywords

    def list_devices(self) -> List[AudioDevice]:
        if sd is None:
            logger.warning("sounddevice nie jest dostępne - brak urządzeń %s", self.backend.value)
            return []

        devices: List[AudioDevice] = []
        default_output = None
        try:
            default_setting = sd.default.device
            if isinstance(default_setting, (list, tuple)) and len(default_setting) > 1:
                default_output = default_setting[1]
        except Exception:  # pragma: no cover - konfiguracje bez domyślnego urządzenia
            default_output = None

        try:
            hostapis = sd.query_hostapis()
            for index, info in enumerate(sd.query_devices()):
                host_name = hostapis[info["hostapi"]]["name"]
                if not any(keyword.lower() in host_name.lower() for keyword in self._keywords):
                    continue
                if info.get("max_output_channels", 0) <= 0:
                    continue
                device_id = f"{self.backend.value}:{index}"
                devices.append(
                    AudioDevice(
                        id=device_id,
                        name=info["name"],
                        backend=self.backend,
                        raw_index=index,
                        is_default=default_output == index,
                    )
                )
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Nie udało się pobrać urządzeń %s: %s", self.backend.value, exc)
        return devices

    def create_player(self, device: AudioDevice) -> Player:
        try:
            stream_kwargs = {"blocksize": 1024, "latency": "low"}
            return SoundDevicePlayer(device, stream_kwargs=stream_kwargs)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Nie udało się stworzyć SoundDevicePlayer dla %s: %s", device.name, exc)
            return MockPlayer(device)

