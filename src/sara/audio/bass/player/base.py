"""Core BASS player implementation."""

from __future__ import annotations

import logging
import os
import threading
from typing import Callable, Optional

from sara.audio.bass.manager import BassManager, _DeviceContext
from sara.audio.bass.player_monitor import start_monitor as _start_monitor_impl

from . import flow as _flow
from . import mix_trigger as _mix_trigger

logger = logging.getLogger("sara.audio.bass.player_base")

_DEBUG_LOOP = bool(os.environ.get("SARA_DEBUG_LOOP"))
_LOOP_GUARD_BASE_SLACK = 0.001
_LOOP_GUARD_FALLBACK_SLACK = 0.001


class BassPlayer:
    """Implementacja Player korzystająca z BASS."""

    # Bardzo mały interwał, żeby zdarzenia miksu/pętli były możliwie precyzyjne.
    _MONITOR_INTERVAL = 0.001

    play = _flow.play
    pause = _flow.pause
    stop = _flow.stop
    fade_out = _flow.fade_out
    _jump_to_loop_start = _flow.jump_to_loop_start

    _apply_mix_trigger = _mix_trigger.apply_mix_trigger
    set_mix_trigger = _mix_trigger.set_mix_trigger

    def __init__(self, manager: BassManager, device_index: int) -> None:
        self._manager = manager
        self._device_index = device_index
        self._device_context: Optional[_DeviceContext] = None
        self._stream: int = 0
        self._current_item_id: Optional[str] = None
        self._gain_factor: float = 1.0
        self._loop_start: Optional[float] = None
        self._loop_end: Optional[float] = None
        self._loop_active: bool = False
        self._loop_sync_handle: int = 0
        self._loop_sync_proc = None
        self._loop_alt_sync_handle: int = 0
        self._loop_alt_sync_proc = None
        self._loop_end_sync_handle: int = 0
        self._loop_end_sync_proc = None
        self._loop_start_bytes: int = 0
        self._loop_end_bytes: int = 0
        self._debug_loop = _DEBUG_LOOP
        self._mix_sync_handle: int = 0
        self._mix_sync_proc = None
        self._mix_callback: Optional[Callable[[], None]] = None
        self._finished_callback: Optional[Callable[[str], None]] = None
        self._progress_callback: Optional[Callable[[str, float], None]] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_stop = threading.Event()
        self._fade_thread: Optional[threading.Thread] = None
        self._start_offset: float = 0.0
        # zachowujemy schowany timer z dawnych implementacji, żeby unikać attribute error
        self._loop_fake_timer = None
        self._last_loop_jump_ts: float = 0.0
        self._loop_guard_enabled: bool = True
        self._last_loop_debug_log: float = 0.0
        self._last_progress_ts: float = 0.0
        self._loop_iteration: int = 0
        self._loop_guard_armed: bool = False
        # zapewnij kompatybilność, nawet jeśli stary obiekt był zcache'owany
        if not hasattr(self, "_apply_loop_settings"):
            self._apply_loop_settings = lambda: None  # type: ignore[attr-defined]
        if not hasattr(self, "set_loop"):
            # minimalny set_loop dla starych instancji
            def _compat_set_loop(start_seconds, end_seconds):
                self._loop_start = start_seconds
                self._loop_end = end_seconds
                self._loop_active = bool(
                    start_seconds is not None
                    and end_seconds is not None
                    and end_seconds > start_seconds
                )

            self.set_loop = _compat_set_loop  # type: ignore[attr-defined]

    def _start_monitor(self) -> None:
        _start_monitor_impl(
            self,
            monitor_interval=self._MONITOR_INTERVAL,
            loop_guard_base_slack=_LOOP_GUARD_BASE_SLACK,
            loop_guard_fallback_slack=_LOOP_GUARD_FALLBACK_SLACK,
            logger=logger,
        )

    def set_finished_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        self._finished_callback = callback

    def set_progress_callback(self, callback: Optional[Callable[[str, float], None]]) -> None:
        self._progress_callback = callback

    def set_mix_callback(self, callback: Optional[Callable[[], None]]) -> None:
        self._mix_callback = callback

    def get_length_seconds(self) -> float:
        try:
            return float(self._manager.channel_get_length_seconds(self._stream))
        except Exception:
            return 0.0

    def set_gain_db(self, gain_db: Optional[float]) -> None:
        if gain_db is None:
            self._gain_factor = 1.0
        else:
            try:
                gain = max(min(gain_db, 18.0), -60.0)
                self._gain_factor = float(10 ** (gain / 20.0))
            except Exception:  # pragma: no cover - defensywne
                self._gain_factor = 1.0
        self._apply_gain()

    def _apply_gain(self) -> None:
        if self._stream:
            self._manager.channel_set_volume(self._stream, self._gain_factor)

    def _is_active(self) -> bool:
        return self._manager.channel_is_active(self._stream)

    def is_active(self) -> bool:
        return self._is_active()

    def supports_mix_trigger(self) -> bool:
        return True

