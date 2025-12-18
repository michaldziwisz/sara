"""Audio engine type definitions.

Extracted from `sara.audio.engine` to keep that module smaller and to avoid
importing heavyweight backends when only the shared types are needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import Event
from typing import Callable, List, Optional, Protocol


class BackendType(Enum):
    WASAPI = "wasapi"
    ASIO = "asio"
    BASS = "bass"
    BASS_ASIO = "bass-asio"


@dataclass
class AudioDevice:
    id: str
    name: str
    backend: BackendType
    raw_index: Optional[int] = None
    is_default: bool = False


class Player(Protocol):
    def play(
        self,
        playlist_item_id: str,
        source_path: str,
        *,
        start_seconds: float = 0.0,
        allow_loop: bool = True,
        mix_trigger_seconds: Optional[float] = None,
        on_mix_trigger: Optional[Callable[[], None]] = None,
    ) -> Optional[Event]: ...

    def is_active(self) -> bool: ...

    def pause(self) -> None: ...

    def stop(self) -> None: ...

    def fade_out(self, duration: float) -> None: ...

    def set_finished_callback(self, callback: Optional[Callable[[str], None]]) -> None: ...

    def set_progress_callback(self, callback: Optional[Callable[[str, float], None]]) -> None: ...

    def set_mix_trigger(
        self,
        mix_trigger_seconds: Optional[float],
        on_mix_trigger: Optional[Callable[[], None]],
    ) -> None: ...

    def set_gain_db(self, gain_db: Optional[float]) -> None: ...

    def set_loop(self, start_seconds: Optional[float], end_seconds: Optional[float]) -> None: ...

    def supports_mix_trigger(self) -> bool: ...


class BackendProvider(Protocol):
    backend: BackendType

    def list_devices(self) -> List[AudioDevice]: ...

    def create_player(self, device: AudioDevice) -> Player: ...

