"""BASS ASIO player implementation."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .manager import BassManager, _AsioDeviceContext, _DeviceContext
from .player_base import BassPlayer

logger = logging.getLogger(__name__)


class BassAsioPlayer(BassPlayer):
    """Player wykorzystujący BASS ASIO (bassasio.dll)."""

    def __init__(self, manager: BassManager, device_index: int, channel_start: int = 0) -> None:
        super().__init__(manager, device_index)
        self._channel_start = max(0, channel_start)
        self._asio_context: Optional[_AsioDeviceContext] = None
        self._stream_total_seconds: float = 0.0
        self._use_asio = True
        # osobny kontekst BASS do tworzenia strumienia decode (no-sound)
        self._decode_device_context: Optional[_DeviceContext] = None
        self._gain_factor = 1.0
        # dla ASIO polegamy na syncach, pythonowy guard wyłączony
        self._loop_guard_enabled = False
        # własne callbacki ASIO
        self._asio_finished_callback: Optional[Callable[[str], None]] = None
        self._asio_mix_callback: Optional[Callable[[], None]] = None
        self._asio_mix_trigger = None

    def _is_active(self) -> bool:
        try:
            if self._progress_callback and self._current_item_id:
                pos = self._manager.channel_get_seconds(self._stream)
                self._progress_callback(self._current_item_id, pos)
        except Exception:
            pass
        return self._manager.asio_is_active(self._device_index)

    def is_active(self) -> bool:
        return self._is_active()

    def get_length_seconds(self) -> float:
        try:
            return float(self._stream_total_seconds)
        except Exception:
            return 0.0

    def play(
        self,
        playlist_item_id: str,
        source_path: str,
        *,
        start_seconds: float = 0.0,
        allow_loop: bool = True,
        mix_trigger_seconds: Optional[float] = None,
        on_mix_trigger: Optional[Callable[[], None]] = None,
    ) -> Optional[threading.Event]:
        # ASIO wymaga kanału w trybie decode
        self.stop()
        self._current_item_id = playlist_item_id
        path = Path(source_path)
        self._asio_context = self._manager.acquire_asio_device(self._device_index)
        decode_device_index = 0  # BASS „No sound”
        self._decode_device_context = None
        try:
            self._decode_device_context = self._manager.acquire_device(decode_device_index)
        except Exception as exc:
            logger.debug("BASS ASIO: nie udało się zainicjować urządzenia decode %s: %s", decode_device_index, exc)
        self._stream = self._manager.stream_create_file(
            decode_device_index,
            path,
            # ustaw SAMPLE_LOOP, żeby strumień decode nie zatrzymał się po dojściu do końca
            allow_loop=True,
            decode=True,
            set_device=self._decode_device_context is not None,
        )
        self._start_offset = 0.0
        if start_seconds > 0:
            self._manager.channel_set_position(self._stream, start_seconds)
            self._start_offset = float(start_seconds)
        self._apply_gain()
        self._loop_active = bool(self._loop_start is not None and self._loop_end is not None)
        self._last_loop_jump_ts = 0.0
        try:
            self._stream_total_seconds = self._manager.channel_get_length_seconds(self._stream)
        except Exception:
            self._stream_total_seconds = 0.0
        self._apply_loop_settings()
        self._apply_mix_trigger(mix_trigger_seconds, on_mix_trigger)
        # zamiast ChannelPlay włączamy ASIO render BASS decode
        try:
            self._manager.asio_play_stream(self._device_index, self._stream, channel_start=self._channel_start)
        except Exception as exc:
            logger.error(
                "BASS ASIO start failed device=%s ch=%s err=%s",
                self._device_index,
                self._channel_start,
                exc,
            )
            self.stop()
            raise
        self._start_monitor()
        return None

    def stop(self, *, _from_fade: bool = False) -> None:
        try:
            self._manager.asio_stop(self._device_index)
        except Exception:
            pass
        super().stop(_from_fade=_from_fade)
        if self._asio_context:
            self._asio_context.release()
            self._asio_context = None
        if self._decode_device_context:
            try:
                self._decode_device_context.release()
            except Exception:
                pass
            self._decode_device_context = None

    def _apply_gain(self) -> None:
        try:
            self._manager.asio_set_volume(self._device_index, self._channel_start, self._gain_factor)
        except Exception:
            pass

    def fade_out(self, duration: float) -> None:
        if not self._stream:
            return
        target_stream = self._stream
        if self._fade_thread and self._fade_thread.is_alive():
            return
        start_ts = time.perf_counter()
        finished_item_id = self._current_item_id

        def _runner():
            nonlocal target_stream
            steps = max(4, int(duration / 0.05))
            interrupted = False
            initial = self._gain_factor
            try:
                logger.debug(
                    "ASIO fade start stream=%s duration=%.3f gain=%.3f steps=%d",
                    target_stream,
                    duration,
                    initial,
                    steps,
                )
                for i in range(steps):
                    if self._stream != target_stream:
                        interrupted = True
                        break
                    factor = initial * (1.0 - float(i + 1) / steps)
                    self._gain_factor = factor
                    try:
                        self._manager.asio_set_volume(self._device_index, self._channel_start, factor)
                    except Exception:
                        interrupted = True
                        break
                    time.sleep(duration / steps)
            finally:
                elapsed = time.perf_counter() - start_ts
                completed = not interrupted and self._stream == target_stream
                logger.debug(
                    "ASIO fade done stream=%s requested=%.3f elapsed=%.3f completed=%s",
                    target_stream,
                    duration,
                    elapsed,
                    completed,
                )
                if completed:
                    self.stop(_from_fade=True)
                    if self._finished_callback and finished_item_id:
                        try:
                            self._finished_callback(finished_item_id)
                        except Exception:
                            pass

        self._fade_thread = threading.Thread(target=_runner, daemon=True)
        self._fade_thread.start()

    def set_loop(self, start_seconds: Optional[float], end_seconds: Optional[float]) -> None:
        if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
            self._loop_start = None
            self._loop_end = None
            self._loop_active = False
            self._last_loop_jump_ts = 0.0
            self._loop_iteration = 0
            self._loop_guard_armed = False
            if self._loop_sync_handle and self._stream:
                self._manager.channel_remove_sync(self._stream, self._loop_sync_handle)
            self._loop_sync_handle = 0
            self._loop_sync_proc = None
            return
        self._loop_start = start_seconds
        self._loop_end = end_seconds
        self._loop_active = True
        self._last_loop_jump_ts = 0.0
        self._loop_iteration = 0
        self._loop_guard_armed = False
        self._apply_loop_settings()

    def _apply_loop_settings(self) -> None:
        if not self._stream:
            return
        if self._loop_sync_handle:
            self._manager.channel_remove_sync(self._stream, self._loop_sync_handle)
            self._loop_sync_handle = 0
            self._loop_sync_proc = None
        if hasattr(self, "_loop_alt_sync_handle") and self._loop_alt_sync_handle:
            self._manager.channel_remove_sync(self._stream, self._loop_alt_sync_handle)
            self._loop_alt_sync_handle = 0
            self._loop_alt_sync_proc = None
        if hasattr(self, "_loop_end_sync_handle") and self._loop_end_sync_handle:
            self._manager.channel_remove_sync(self._stream, self._loop_end_sync_handle)
            self._loop_end_sync_handle = 0
            self._loop_end_sync_proc = None
        if self._loop_fake_timer:
            self._loop_fake_timer.cancel()
            self._loop_fake_timer = None
        if not self._loop_active or self._loop_end is None or self._loop_start is None:
            return

        start = max(0.0, self._loop_start)
        end = max(start + 0.001, self._loop_end)
        self._loop_iteration = 0
        self._loop_start_bytes = self._manager.seconds_to_bytes(self._stream, start)
        self._loop_end_bytes = self._manager.seconds_to_bytes(self._stream, end)
        if self._debug_loop:
            logger.debug(
                "Loop debug: apply loop start=%.6fs end=%.6fs start_bytes=%s end_bytes=%s stream=%s",
                start,
                end,
                self._loop_start_bytes,
                self._loop_end_bytes,
                self._stream,
            )

        # Synci wyłączone – stawiamy na pętlę programową z monitra
        def _sync_cb(handle, channel, data, user):
            try:
                self._jump_to_loop_start("sync")
            except Exception as exc:
                if self._debug_loop:
                    logger.debug("Loop debug: sync jump failed: %s", exc)

        # rejestruj dwa synchro: zwykłe oraz MIXTIME, żeby dać BASS więcej szans
        try:
            self._loop_sync_proc = self._manager.make_sync_proc(_sync_cb)
            self._loop_sync_handle = self._manager.channel_set_sync_pos(
                self._stream, self._loop_end_bytes, self._loop_sync_proc, is_bytes=True, mix_time=False
            )
        except Exception as exc:
            self._loop_sync_proc = None
            self._loop_sync_handle = 0
            if self._debug_loop:
                logger.debug("Loop debug: failed to set sync pos: %s", exc)
        try:
            self._loop_alt_sync_proc = self._manager.make_sync_proc(_sync_cb)
            self._loop_alt_sync_handle = self._manager.channel_set_sync_pos(
                self._stream, self._loop_end_bytes, self._loop_alt_sync_proc, is_bytes=True, mix_time=True
            )
        except Exception as exc:
            self._loop_alt_sync_proc = None
            self._loop_alt_sync_handle = 0
            if self._debug_loop:
                logger.debug("Loop debug: failed to set alt sync pos: %s", exc)
        self._loop_end_sync_proc = None
        self._loop_end_sync_handle = 0
        if self._debug_loop:
            logger.debug("Loop debug: sync+guard active")

    def supports_mix_trigger(self) -> bool:
        return True
