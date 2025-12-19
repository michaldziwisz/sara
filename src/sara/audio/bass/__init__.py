"""Integracja z biblioteką BASS (jeśli dostępna)."""

from __future__ import annotations

from .backends import BassAsioBackend, BassBackend
from .manager import BassManager
from .native import BassNotAvailable
from .player_base import BassPlayer

__all__ = [
    "BassAsioBackend",
    "BassAsioPlayer",
    "BassBackend",
    "BassManager",
    "BassNotAvailable",
    "BassPlayer",
]


def __getattr__(name: str):  # pragma: no cover - import-time helper
    if name == "BassAsioPlayer":
        from .asio_player import BassAsioPlayer

        return BassAsioPlayer
    raise AttributeError(name)
