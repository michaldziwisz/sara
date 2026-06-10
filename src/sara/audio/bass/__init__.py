"""Integracja z biblioteką BASS (jeśli dostępna)."""

from __future__ import annotations

from .backends import BassAsioBackend, BassBackend
from .manager import BassManager
from .native import BassNotAvailable
from .player_base import BassPlayer

_DEBUG_LOOP = False

__all__ = [
    "BassAsioBackend",
    "BassAsioPlayer",
    "BassBackend",
    "BassManager",
    "BassNotAvailable",
    "BassPlayer",
    "set_debug_loop",
]


def set_debug_loop(enabled: bool) -> None:
    """Apply loop-debug diagnostics to the concrete BASS player module."""

    global _DEBUG_LOOP  # pylint: disable=global-statement
    enabled = bool(enabled)
    _DEBUG_LOOP = enabled

    from sara.audio.bass.player import base as player_base_mod

    player_base_mod._DEBUG_LOOP = enabled  # pylint: disable=protected-access
    try:
        import sara.audio.bass.player_base as compat_player_base_mod

        compat_player_base_mod._DEBUG_LOOP = enabled  # pylint: disable=protected-access
    except Exception:
        pass
    try:
        import sara.audio.bass_player_base as legacy_player_base_mod

        legacy_player_base_mod._DEBUG_LOOP = enabled  # pylint: disable=protected-access
    except Exception:
        pass


def __getattr__(name: str):  # pragma: no cover - import-time helper
    if name == "BassAsioPlayer":
        from .asio_player import BassAsioPlayer

        return BassAsioPlayer
    raise AttributeError(name)
