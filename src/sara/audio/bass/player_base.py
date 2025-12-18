"""Implementacje playerów opartych o BASS."""

from __future__ import annotations

import ctypes
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .manager import BassManager, _AsioDeviceContext, _DeviceContext
from .native import BassNotAvailable, _BassConstants

logger = logging.getLogger(__name__)
_DEBUG_LOOP = bool(os.environ.get("SARA_DEBUG_LOOP"))
_LOOP_GUARD_BASE_SLACK = 0.001
_LOOP_GUARD_FALLBACK_SLACK = 0.001


class BassPlayer:
    """Implementacja Player korzystająca z BASS."""

    # Bardzo mały interwał, żeby zdarzenia miksu/pętli były możliwie precyzyjne.
    _MONITOR_INTERVAL = 0.001

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

    # --- lifecycle ---
    def play(
        self,
        playlist_item_id: str,
        source_path: str,
        *,
        start_seconds: float = 0.0,
        allow_loop: bool = False,
        mix_trigger_seconds: Optional[float] = None,
        on_mix_trigger: Optional[Callable[[], None]] = None,
    ) -> Optional[threading.Event]:
        self.stop()
        self._current_item_id = playlist_item_id
        path = Path(source_path)
        self._device_context = self._manager.acquire_device(self._device_index)
        self._stream = self._manager.stream_create_file(self._device_index, path, allow_loop=allow_loop)
        self._start_offset = 0.0
        if start_seconds > 0:
            self._manager.channel_set_position(self._stream, start_seconds)
            self._start_offset = float(start_seconds)
        self._apply_gain()
        self._manager.channel_play(self._stream, False)
        self._loop_active = bool(self._loop_start is not None and self._loop_end is not None)
        self._last_loop_jump_ts = 0.0
        self._apply_loop_settings()
        self._apply_mix_trigger(mix_trigger_seconds, on_mix_trigger)
        self._start_monitor()
        return None

    def pause(self) -> None:
        if self._stream:
            self._manager.channel_pause(self._stream)

    def stop(self, *, _from_fade: bool = False) -> None:
        self._monitor_stop.set()
        if self._fade_thread and self._fade_thread.is_alive() and not _from_fade:
            self._fade_thread.join(timeout=0.5)
        if not _from_fade:
            self._fade_thread = None
        if self._stream:
            try:
                if getattr(self, "_use_asio", False):
                    self._manager.asio_stop(self._device_index)
            except Exception:
                pass
            self._manager.channel_stop(self._stream)
            if self._loop_sync_handle:
                self._manager.channel_remove_sync(self._stream, self._loop_sync_handle)
                self._loop_sync_handle = 0
                self._loop_sync_proc = None
            if hasattr(self, "_loop_end_sync_handle") and self._loop_end_sync_handle:
                self._manager.channel_remove_sync(self._stream, self._loop_end_sync_handle)
                self._loop_end_sync_handle = 0
            self._loop_end_sync_proc = None
            if hasattr(self, "_loop_alt_sync_handle") and self._loop_alt_sync_handle:
                self._manager.channel_remove_sync(self._stream, self._loop_alt_sync_handle)
                self._loop_alt_sync_handle = 0
                self._loop_alt_sync_proc = None
            if self._mix_sync_handle:
                self._manager.channel_remove_sync(self._stream, self._mix_sync_handle)
                self._mix_sync_handle = 0
                self._mix_sync_proc = None
            self._manager.stream_free(self._stream)
            self._stream = 0
        if self._device_context:
            self._device_context.release()
            self._device_context = None
        if getattr(self, "_asio_context", None):
            self._asio_context.release()
            self._asio_context = None
        self._current_item_id = None
        self._loop_active = False
        self._start_offset = 0.0
        if self._monitor_thread and self._monitor_thread.is_alive() and not _from_fade:
            self._monitor_thread.join(timeout=0.5)
        self._monitor_thread = None
        self._monitor_stop.clear()
        if _from_fade:
            self._fade_thread = None

    def _start_monitor(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_stop.clear()

        def _runner() -> None:
            while not self._monitor_stop.is_set():
                try:
                    if self._stream:
                        now = time.time()
                        if (
                            self._progress_callback
                            and self._current_item_id
                            and (now - self._last_progress_ts) >= 0.05
                        ):
                            try:
                                pos = self._manager.channel_get_seconds(self._stream)
                                self._progress_callback(self._current_item_id, pos)
                            except Exception:
                                pass
                            self._last_progress_ts = now
                        # nadzoruj pętlę również po stronie Python, żeby uniknąć pominiętych synców
                        if (
                            self._loop_guard_enabled
                            and self._loop_active
                            and self._loop_end is not None
                            and self._loop_start is not None
                        ):
                            try:
                                pos = self._manager.channel_get_seconds(self._stream)
                                now = time.time()
                                if self._debug_loop and (now - self._last_loop_debug_log) > 0.5:
                                    logger.debug(
                                        "Loop debug: pos=%.6f start=%.6f end=%.6f stream=%s",
                                        pos,
                                        self._loop_start,
                                        self._loop_end,
                                        self._stream,
                                    )
                                    self._last_loop_debug_log = now
                                # strażnik awaryjny: pozwól syncowi zadziałać, a reaguj dopiero PO końcu
                                if (now - self._last_loop_jump_ts) > 0.004:
                                    guard_slack = (
                                        _LOOP_GUARD_BASE_SLACK if self._loop_guard_armed else _LOOP_GUARD_FALLBACK_SLACK
                                    )
                                    if pos > (self._loop_end + guard_slack):
                                        self._jump_to_loop_start("guard", pos)
                                        continue
                                    # twardy clamp tylko przy dużym odjechaniu
                                    if pos > (self._loop_end + 0.05):
                                        self._jump_to_loop_start("clamp", pos)
                                        continue
                            except Exception as exc:
                                if self._debug_loop:
                                    logger.debug("Loop debug: guard check failed: %s", exc)
                        active = self._is_active()
                        if not active:
                            # Jeśli pętla ma być aktywna, próbujemy wznowić bez wyzwalania zakończenia
                            if self._loop_active and self._stream:
                                try:
                                    if self._loop_start_bytes:
                                        self._manager.channel_set_position_bytes(self._stream, self._loop_start_bytes)
                                    # jeśli strumień nie gra, wznów go
                                    try:
                                        self._manager.channel_play(self._stream, False)
                                    except Exception:
                                        pass
                                except Exception as exc:
                                    if self._debug_loop:
                                        logger.debug("Loop debug: monitor restart failed: %s", exc)
                                # nawet jeśli się nie udało, nie zgłaszaj zakończenia – próbuj ponownie
                                time.sleep(self._MONITOR_INTERVAL)
                                continue
                            if self._finished_callback and self._current_item_id:
                                try:
                                    self._finished_callback(self._current_item_id)
                                except Exception:
                                    pass
                            # zwolnij zasoby po naturalnym zakończeniu
                            try:
                                self.stop(_from_fade=True)
                            except Exception:
                                pass
                            break
                    time.sleep(self._MONITOR_INTERVAL)
                except Exception:
                    break
        self._monitor_thread = threading.Thread(target=_runner, daemon=True, name="bass-monitor")
        self._monitor_thread.start()

    def _jump_to_loop_start(self, reason: str, pos: Optional[float] = None) -> None:
        """Przeskocz na początek pętli i zinstrumentuj przebiegi."""
        if not self._stream or self._loop_start is None:
            return
        self._last_loop_jump_ts = time.time()
        self._loop_iteration = getattr(self, "_loop_iteration", 0) + 1
        if self._loop_start_bytes:
            self._manager.channel_set_position_bytes(self._stream, self._loop_start_bytes)
        else:
            self._manager.channel_set_position(self._stream, self._loop_start)
        post_pos = None
        try:
            post_pos = self._manager.channel_get_seconds(self._stream)
            drift = abs(post_pos - self._loop_start)
            if drift > 0.002:
                if self._loop_start_bytes:
                    self._manager.channel_set_position_bytes(self._stream, self._loop_start_bytes)
                else:
                    self._manager.channel_set_position(self._stream, self._loop_start)
                post_pos = self._manager.channel_get_seconds(self._stream)
        except Exception:
            pass
        if self._debug_loop:
            logger.debug(
                "Loop debug: jump #%s reason=%s pos=%.6f post=%.6f start=%.6f end=%.6f stream=%s",
                self._loop_iteration,
                reason,
                pos if pos is not None else -1.0,
                post_pos if post_pos is not None else -1.0,
                self._loop_start,
                self._loop_end,
                self._stream,
            )
        if not self._loop_guard_armed:
            self._loop_guard_armed = True

    def _apply_mix_trigger(self, target_seconds: Optional[float], callback: Optional[Callable[[], None]]) -> None:
        if callback is not None and not callable(callback):
            logger.debug("BASS mix trigger: non-callable callback of type %s ignored", type(callback))
            callback = None
        self._mix_callback = callback
        if not target_seconds or not self._stream:
            return
        original_target = float(target_seconds)
        clamped_target = original_target
        try:
            length_seconds = self._manager.channel_get_length_seconds(self._stream)
        except Exception:
            length_seconds = 0.0
        if length_seconds > 0.0 and clamped_target > (length_seconds - 0.01):
            clamped_target = max(0.0, length_seconds - 0.01)
        effective_target = clamped_target
        if self._start_offset > 0.0:
            effective_target = max(0.0, clamped_target - self._start_offset)
        try:
            target_bytes = self._manager.seconds_to_bytes(self._stream, effective_target)
        except Exception as exc:
            logger.debug("BASS mix trigger: failed to convert seconds to bytes: %s", exc)
            return

        def _sync_proc(hsync, channel, data, user):  # pragma: no cover - C callback
            fired_pos = None
            try:
                fired_pos = self._manager.channel_get_seconds(channel)
            except Exception:
                fired_pos = None
            if self._mix_callback:
                try:
                    self._mix_callback()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("BASS mix trigger callback error: %s", exc)
            logger.debug(
                "BASS mix trigger fired stream=%s target=%.3f pos=%s",
                channel,
                clamped_target,
                f"{fired_pos:.3f}" if fired_pos is not None else "unknown",
            )

        self._mix_sync_proc = self._manager.make_sync_proc(_sync_proc)
        try:
            self._mix_sync_handle = self._manager.channel_set_sync_pos(
                self._stream, target_bytes, self._mix_sync_proc, is_bytes=True, mix_time=False
            )
            logger.debug(
                "BASS mix trigger set stream=%s target=%.3f effective=%.3f offset=%.3f (requested=%.3f) callback=%s",
                self._stream,
                clamped_target,
                effective_target,
                self._start_offset,
                original_target,
                "set" if callback else "none",
            )
        except Exception as exc:
            logger.debug("BASS mix trigger: failed to set sync: %s", exc)
            self._mix_sync_proc = None
            self._mix_sync_handle = 0

    def fade_out(self, duration: float) -> None:
        if duration <= 0 or not self._stream:
            self.stop()
            return

        target_stream = self._stream
        start_ts = time.perf_counter()

        def _runner(target: int) -> None:
            steps = max(4, int(duration / 0.05))
            interrupted = False
            try:
                initial = self._gain_factor
                logger.debug(
                    "BASS fade start stream=%s duration=%.3f gain=%.3f steps=%d",
                    target,
                    duration,
                    initial,
                    steps,
                )
                for i in range(steps):
                    if self._stream != target:
                        interrupted = True
                        break
                    factor = initial * (1.0 - float(i + 1) / steps)
                    try:
                        self._manager.channel_set_volume(target, factor)
                    except Exception as exc:
                        logger.debug("BASS fade step failed: %s", exc)
                        interrupted = True
                        break
                    time.sleep(duration / steps)
            finally:
                elapsed = time.perf_counter() - start_ts
                completed = not interrupted and self._stream == target
                logger.debug(
                    "BASS fade done stream=%s requested=%.3f elapsed=%.3f completed=%s",
                    target,
                    duration,
                    elapsed,
                    completed,
                )
                if interrupted or self._stream != target:
                    try:
                        self._manager.channel_set_volume(target, self._gain_factor)
                    except Exception:
                        pass
                else:
                    self.stop(_from_fade=True)

        self._fade_thread = threading.Thread(target=_runner, args=(target_stream,), daemon=True)
        self._fade_thread.start()

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

    def set_mix_trigger(
        self,
        mix_trigger_seconds: Optional[float],
        on_mix_trigger: Optional[Callable[[], None]],
    ) -> None:
        # usuń istniejący sync i ustaw nowy, jeśli podany
        if self._stream and self._mix_sync_handle:
            try:
                self._manager.channel_remove_sync(self._stream, self._mix_sync_handle)
            except Exception:
                pass
            self._mix_sync_handle = 0
            self._mix_sync_proc = None
        self._apply_mix_trigger(mix_trigger_seconds, on_mix_trigger)

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
