"""Core BASS player implementation."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
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
        self._preloaded_stream: int = 0
        self._preloaded_device_context: Optional[_DeviceContext] = None
        self._preloaded_path: Path | None = None
        self._preloaded_start_seconds: float = 0.0
        self._preloaded_allow_loop: bool = False
        self._preload_lock = threading.Lock()
        self._preload_generation: int = 0
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

    def preload(self, source_path: str, *, start_seconds: float = 0.0, allow_loop: bool = False) -> bool:
        """Prepare a stream for `play()` to start with minimal I/O latency.

        This is best-effort and backend-specific: it creates and keeps an additional
        BASS stream handle around (without starting playback) so that `play()` can
        reuse it later if the same path/start/loop values are requested.
        """
        path = Path(source_path)
        if not path.exists():
            return False

        start_seconds = max(0.0, float(start_seconds or 0.0))
        allow_loop = bool(allow_loop)

        with self._preload_lock:
            self._preload_generation += 1
            generation = self._preload_generation

        device_context: _DeviceContext | None = None
        stream: int = 0
        try:
            device_context = self._manager.acquire_device(self._device_index)
            stream = self._manager.stream_create_file(self._device_index, path, allow_loop=allow_loop)
            if start_seconds > 0.0:
                self._manager.channel_set_position(stream, start_seconds)
            try:
                self._manager.channel_set_volume(stream, self._gain_factor)
            except Exception:
                pass
        except Exception:
            if stream:
                try:
                    self._manager.stream_free(stream)
                except Exception:
                    pass
            if device_context:
                try:
                    device_context.release()
                except Exception:
                    pass
            return False

        with self._preload_lock:
            if generation != self._preload_generation:
                stale_stream = stream
                stale_context = device_context
                stream = 0
                device_context = None
            else:
                stale_stream, stale_context = self._preloaded_stream, self._preloaded_device_context
                self._preloaded_stream = stream
                self._preloaded_device_context = device_context
                self._preloaded_path = path
                self._preloaded_start_seconds = start_seconds
                self._preloaded_allow_loop = allow_loop
                stream = 0
                device_context = None

        if stale_stream:
            try:
                self._manager.stream_free(stale_stream)
            except Exception:
                pass
        if stale_context:
            try:
                stale_context.release()
            except Exception:
                pass
        return True

    def _consume_preloaded(
        self,
        path: Path,
        *,
        start_seconds: float,
        allow_loop: bool,
        tolerance: float = 0.001,
    ) -> tuple[int, _DeviceContext | None] | None:
        """Return the prepared stream when it matches, otherwise clear stale preload.

        Always invalidates any in-flight `preload()` calls so late results get dropped.
        """
        stale_stream: int = 0
        stale_context: _DeviceContext | None = None
        consumed: tuple[int, _DeviceContext | None] | None = None
        with self._preload_lock:
            self._preload_generation += 1
            if (
                self._preloaded_stream
                and self._preloaded_path == path
                and self._preloaded_allow_loop == bool(allow_loop)
                and abs(float(start_seconds) - float(self._preloaded_start_seconds)) <= tolerance
            ):
                consumed = (self._preloaded_stream, self._preloaded_device_context)
                self._preloaded_stream = 0
                self._preloaded_device_context = None
                self._preloaded_path = None
                self._preloaded_start_seconds = 0.0
                self._preloaded_allow_loop = False
            elif self._preloaded_stream:
                stale_stream, stale_context = self._preloaded_stream, self._preloaded_device_context
                self._preloaded_stream = 0
                self._preloaded_device_context = None
                self._preloaded_path = None
                self._preloaded_start_seconds = 0.0
                self._preloaded_allow_loop = False

        if stale_stream:
            try:
                self._manager.stream_free(stale_stream)
            except Exception:
                pass
        if stale_context:
            try:
                stale_context.release()
            except Exception:
                pass
        return consumed

    def _drop_preloaded(self) -> None:
        """Release any prepared stream and cancel in-flight preload requests."""
        stale_stream: int = 0
        stale_context: _DeviceContext | None = None
        with self._preload_lock:
            self._preload_generation += 1
            if self._preloaded_stream:
                stale_stream, stale_context = self._preloaded_stream, self._preloaded_device_context
                self._preloaded_stream = 0
                self._preloaded_device_context = None
                self._preloaded_path = None
                self._preloaded_start_seconds = 0.0
                self._preloaded_allow_loop = False
        if stale_stream:
            try:
                self._manager.stream_free(stale_stream)
            except Exception:
                pass
        if stale_context:
            try:
                stale_context.release()
            except Exception:
                pass

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
