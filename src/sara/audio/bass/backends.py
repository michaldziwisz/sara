"""BASS backend providers used by `AudioEngine`."""

from __future__ import annotations

import logging
from typing import List

from .manager import BassManager
from .native import BassNotAvailable
from .player_base import BassPlayer

logger = logging.getLogger(__name__)


class BassBackend:
    """Adapter providera dla AudioEngine."""

    backend = None  # ustawiane przez AudioEngine po imporcie

    def __init__(self) -> None:
        try:
            self._manager = BassManager.instance()
            self.is_available = True
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("BASS backend niedostępny: %s", exc)
            self.is_available = False
            self._manager = None

    def list_devices(self) -> List["AudioDevice"]:
        if not self.is_available or self._manager is None:
            return []
        try:
            return self._manager.list_devices()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Enumeracja urządzeń BASS nie powiodła się: %s", exc)
            return []

    def create_player(self, device: "AudioDevice") -> BassPlayer:
        if not self.is_available or self._manager is None:
            raise BassNotAvailable("BASS backend niedostępny")
        index = device.raw_index
        if index is None:
            try:
                index = int(str(device.id).split(":")[-1])
            except Exception:
                index = 0
        return BassPlayer(self._manager, index)


class BassAsioBackend:
    """Backend BASS ASIO (bassasio.dll)."""

    backend = None  # ustawiane przez AudioEngine

    def __init__(self) -> None:
        try:
            self._manager = BassManager.instance()
            self.is_available = self._manager._asio is not None
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("BASS ASIO backend niedostępny: %s", exc)
            self.is_available = False
            self._manager = None

    def list_devices(self) -> List["AudioDevice"]:
        if not self.is_available or self._manager is None:
            return []
        try:
            return self._manager.list_asio_devices()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Enumeracja urządzeń BASS ASIO nie powiodła się: %s", exc)
            return []

    def create_player(self, device: "AudioDevice") -> BassAsioPlayer:
        if not self.is_available or self._manager is None:
            raise BassNotAvailable("BASS ASIO backend niedostępny")
        from .asio_player import BassAsioPlayer

        index = device.raw_index
        channel_start = 0
        try:
            parts = str(device.id).split(":")
            if len(parts) >= 3:
                channel_start = int(parts[-1])
        except Exception:
            channel_start = 0
        if index is None:
            try:
                index = int(str(device.id).split(":")[-1])
            except Exception:
                index = 0
        return BassAsioPlayer(self._manager, index, channel_start=channel_start)
