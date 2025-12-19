"""Warstwa abstrakcji urządzeń audio (WASAPI/ASIO)."""

from __future__ import annotations

import logging
import os
import warnings
from typing import Dict, List

from sara.audio.mock_backend import MockBackendProvider, MockPlayer
from sara.audio.types import AudioDevice, BackendProvider, BackendType, Player
from sara.core.env import is_e2e_mode

logger = logging.getLogger(__name__)

try:
    from pycaw.pycaw import AudioUtilities
except ImportError:  # pragma: no cover - środowiska bez pycaw
    AudioUtilities = None
else:  # pragma: no cover - tylko gdy pycaw obecny
    warnings.filterwarnings(
        "ignore",
        message="COMError attempting to get property",
        category=UserWarning,
        module="pycaw.utils",
    )

try:
    import clr  # type: ignore
except ImportError:  # pragma: no cover - pythonnet opcjonalny
    clr = None

try:
    from sara.audio.bass import BassBackend, BassAsioBackend
except Exception:  # pragma: no cover - BASS opcjonalny
    BassBackend = None
    BassAsioBackend = None


class PycawBackend:
    """Szkic backendu WASAPI opartego o pycaw."""

    backend = BackendType.WASAPI

    def list_devices(self) -> List[AudioDevice]:
        if AudioUtilities is None:
            logger.debug("pycaw niedostępny - pomijam enumerację WASAPI")
            return []

        devices: List[AudioDevice] = []
        try:
            all_devices = AudioUtilities.GetAllDevices()
            default_device = AudioUtilities.GetSpeakers()
            default_id = getattr(default_device, "id", None)
            for endpoint in all_devices:
                try:
                    state = getattr(endpoint, "State", None)
                    if state not in (0, 1):
                        continue
                    friendly_name = getattr(endpoint, "FriendlyName", "Unknown")
                    endpoint_id = getattr(endpoint, "id", None) or getattr(endpoint, "Id", None)
                    if not endpoint_id:
                        continue
                    devices.append(
                        AudioDevice(
                            id=f"{self.backend.value}:{endpoint_id}",
                            name=str(friendly_name),
                            backend=self.backend,
                            raw_index=None,
                            is_default=endpoint_id == default_id,
                        )
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    logger.debug("Pominięto urządzenie WASAPI: %s", exc)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Enumeracja WASAPI przez pycaw nie powiodła się: %s", exc)
        return devices

    def create_player(self, device: AudioDevice) -> Player:
        try:
            from sara.audio.sounddevice_backend import WasapiPlayer

            return WasapiPlayer(device)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Nie udało się stworzyć playera WASAPI dla %s: %s", device.name, exc)
            return MockPlayer(device)


class AsioBackend:
    """Szkic backendu ASIO z użyciem pythonnet."""

    backend = BackendType.ASIO

    def __init__(self) -> None:
        if clr is not None:
            try:
                clr.AddReference("NAudio")  # pragma: no cover - zależne od środowiska
            except Exception:  # pylint: disable=broad-except
                logger.debug("Biblioteka NAudio nie została załadowana")

    def list_devices(self) -> List[AudioDevice]:
        # TODO: wykorzystać NAudio/ASIO do enumeracji sterowników
        logger.debug("Enumeracja sterowników ASIO wymaga implementacji pythonnet")
        return []

    def create_player(self, device: AudioDevice) -> Player:
        try:
            from sara.audio.sounddevice_backend import AsioPlayer

            return AsioPlayer(device)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Nie udało się stworzyć playera ASIO dla %s: %s", device.name, exc)
            return MockPlayer(device)


class AudioEngine:
    """Zarządza wyborem urządzeń i instancjami playerów."""

    def __init__(self) -> None:
        self._providers: List[BackendProvider] = []
        if is_e2e_mode() or os.environ.get("SARA_FORCE_MOCK_AUDIO"):
            self._providers.append(MockBackendProvider(label="SARA E2E Mock"))
        else:
            backend_cls = BassBackend
            if backend_cls is None:
                try:
                    from sara.audio import bass as _bass_mod  # type: ignore
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Nie udało się zaimportować backendu BASS: %s", exc)
                else:
                    backend_cls = getattr(_bass_mod, "BassBackend", None)
            if backend_cls is None:
                logger.error("Backend BASS nie jest dostępny (brak klasy BassBackend)")
            else:
                try:
                    bass_backend = backend_cls()
                    if getattr(bass_backend, "is_available", False):
                        bass_backend.backend = BackendType.BASS
                        self._providers.append(bass_backend)
                    else:
                        logger.error("Backend BASS niedostępny (is_available=False)")
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Inicjalizacja backendu BASS nie powiodła się: %s", exc)
        # Backend BASS ASIO wyłączony na teraz – zostawiamy tylko standardowy BASS
        if not self._providers:
            logger.warning("Brak dostępnych backendów audio – przełączam na Mock")
            self._providers.append(MockBackendProvider(label="Mock fallback"))
        self._devices: Dict[str, AudioDevice] = {}
        self._players: Dict[str, Player] = {}

    def refresh_devices(self) -> None:
        # wyczyść cache playerów, żeby po zmianach backendu tworzyć świeże instancje
        self._players.clear()
        self._devices.clear()
        all_devices: list[AudioDevice] = []
        for provider in self._providers:
            devices = provider.list_devices()
            if not devices:
                logger.debug("Provider %s nie zwrócił urządzeń", getattr(provider, "backend", provider))
                continue
            for device in devices:
                label = f"{provider.backend.name.lower()}: {device.name}"
                device_labelled = AudioDevice(
                    id=device.id,
                    name=label,
                    backend=device.backend,
                    raw_index=device.raw_index,
                    is_default=device.is_default,
                )
                try:
                    if hasattr(device, "native_samplerate"):
                        device_labelled.native_samplerate = getattr(device, "native_samplerate")
                except Exception:  # pylint: disable=broad-except
                    pass
                self._devices[device.id] = device_labelled
                all_devices.append(device_labelled)
        if all_devices:
            logger.debug(
                "Zarejestrowano %d urządzeń audio: %s",
                len(all_devices),
                ", ".join(f"{d.backend.value}:{d.name}" for d in all_devices),
            )
        else:
            logger.debug("Brak wykrytych urządzeń audio")

    def get_devices(self) -> List[AudioDevice]:
        if not self._devices:
            self.refresh_devices()
        return list(self._devices.values())

    def create_player(self, device_id: str) -> Player:
        device = self._devices.get(device_id)
        if device is None:
            raise ValueError(f"Nieznane urządzenie: {device_id}")

        provider = self._get_provider(device.backend)
        player = provider.create_player(device)
        self._players[device_id] = player
        return player

    def create_player_instance(self, device_id: str) -> Player:
        """Create a new player instance without overwriting the per-device cache.

        This is useful when multiple concurrent players are needed on the same device
        (e.g. overlays), while keeping the legacy create_player() caching behavior.
        """

        if not self._devices:
            self.refresh_devices()
        device = self._devices.get(device_id)
        if device is None:
            raise ValueError(f"Nieznane urządzenie: {device_id}")
        provider = self._get_provider(device.backend)
        return provider.create_player(device)

    def _get_provider(self, backend: BackendType) -> BackendProvider:
        for provider in self._providers:
            if provider.backend is backend:
                return provider
        raise ValueError(f"Brak providera dla backendu {backend}")

    def stop_all(self) -> None:
        for player in list(self._players.values()):
            try:
                player.stop()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Nie udało się zatrzymać playera: %s", exc)
            for clear in (player.set_finished_callback, player.set_progress_callback):
                try:
                    clear(None)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.debug("Nie udało się wyczyścić callbacku playera: %s", exc)


def __getattr__(name: str):  # pragma: no cover - import-time helper
    if name in {"AsioPlayer", "SoundDeviceBackend", "SoundDevicePlayer", "WasapiPlayer"}:
        from sara.audio.sounddevice_backend import (
            AsioPlayer,
            SoundDeviceBackend,
            SoundDevicePlayer,
            WasapiPlayer,
        )

        return {
            "AsioPlayer": AsioPlayer,
            "SoundDeviceBackend": SoundDeviceBackend,
            "SoundDevicePlayer": SoundDevicePlayer,
            "WasapiPlayer": WasapiPlayer,
        }[name]
    raise AttributeError(name)
