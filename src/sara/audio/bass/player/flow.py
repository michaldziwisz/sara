"""Playback lifecycle helpers for `BassPlayer`."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

# Keep the historical logger name for backwards-compatible filtering.
logger = logging.getLogger("sara.audio.bass.player_base")


def play(
    player,
    playlist_item_id: str,
    source_path: str,
    *,
    start_seconds: float = 0.0,
    allow_loop: bool = False,
    mix_trigger_seconds: Optional[float] = None,
    on_mix_trigger: Optional[Callable[[], None]] = None,
) -> Optional[threading.Event]:
    path = Path(source_path)
    start_seconds = max(0.0, float(start_seconds or 0.0))
    allow_loop = bool(allow_loop)
    prepared = None
    consumer = getattr(player, "_consume_preloaded", None)
    if callable(consumer):
        try:
            prepared = consumer(path, start_seconds=start_seconds, allow_loop=allow_loop)
        except Exception:
            prepared = None

    player.stop()
    player._current_item_id = playlist_item_id
    if prepared:
        stream, device_context = prepared
        player._device_context = device_context or player._manager.acquire_device(player._device_index)
        player._stream = stream
    else:
        player._device_context = player._manager.acquire_device(player._device_index)
        player._stream = player._manager.stream_create_file(player._device_index, path, allow_loop=allow_loop)
    player._start_offset = 0.0
    if start_seconds > 0:
        player._manager.channel_set_position(player._stream, start_seconds)
        player._start_offset = float(start_seconds)
    player._apply_gain()
    player._manager.channel_play(player._stream, False)
    player._loop_active = bool(player._loop_start is not None and player._loop_end is not None)
    player._last_loop_jump_ts = 0.0
    player._apply_loop_settings()
    player._apply_mix_trigger(mix_trigger_seconds, on_mix_trigger)
    player._start_monitor()
    return None


def pause(player) -> None:
    if player._stream:
        player._manager.channel_pause(player._stream)


def stop(player, *, _from_fade: bool = False) -> None:
    player._monitor_stop.set()
    if player._fade_thread and player._fade_thread.is_alive() and not _from_fade:
        player._fade_thread.join(timeout=0.5)
    if not _from_fade:
        player._fade_thread = None
    if player._stream:
        try:
            if getattr(player, "_use_asio", False):
                player._manager.asio_stop(player._device_index)
        except Exception:
            pass
        player._manager.channel_stop(player._stream)
        if player._loop_sync_handle:
            player._manager.channel_remove_sync(player._stream, player._loop_sync_handle)
            player._loop_sync_handle = 0
            player._loop_sync_proc = None
        if hasattr(player, "_loop_end_sync_handle") and player._loop_end_sync_handle:
            player._manager.channel_remove_sync(player._stream, player._loop_end_sync_handle)
            player._loop_end_sync_handle = 0
        player._loop_end_sync_proc = None
        if hasattr(player, "_loop_alt_sync_handle") and player._loop_alt_sync_handle:
            player._manager.channel_remove_sync(player._stream, player._loop_alt_sync_handle)
            player._loop_alt_sync_handle = 0
            player._loop_alt_sync_proc = None
        if player._mix_sync_handle:
            player._manager.channel_remove_sync(player._stream, player._mix_sync_handle)
            player._mix_sync_handle = 0
            player._mix_sync_proc = None
        if getattr(player, "_mix_end_sync_handle", 0):
            try:
                player._manager.channel_remove_sync(player._stream, player._mix_end_sync_handle)
            except Exception:
                pass
            player._mix_end_sync_handle = 0
            player._mix_end_sync_proc = None
        player._manager.stream_free(player._stream)
        player._stream = 0
    if player._device_context:
        player._device_context.release()
        player._device_context = None
    if getattr(player, "_asio_context", None):
        player._asio_context.release()
        player._asio_context = None
    player._current_item_id = None
    player._loop_active = False
    player._start_offset = 0.0
    if player._monitor_thread and player._monitor_thread.is_alive() and not _from_fade:
        player._monitor_thread.join(timeout=0.5)
    player._monitor_thread = None
    player._monitor_stop.clear()
    if _from_fade:
        player._fade_thread = None
    if not _from_fade:
        dropper = getattr(player, "_drop_preloaded", None)
        if callable(dropper):
            try:
                dropper()
            except Exception:
                pass


def jump_to_loop_start(player, reason: str, pos: Optional[float] = None) -> None:
    """Przeskocz na początek pętli i zinstrumentuj przebiegi."""
    if not player._stream or player._loop_start is None:
        return
    player._last_loop_jump_ts = time.time()
    player._loop_iteration = getattr(player, "_loop_iteration", 0) + 1
    if player._loop_start_bytes:
        player._manager.channel_set_position_bytes(player._stream, player._loop_start_bytes)
    else:
        player._manager.channel_set_position(player._stream, player._loop_start)
    post_pos = None
    try:
        post_pos = player._manager.channel_get_seconds(player._stream)
        drift = abs(post_pos - player._loop_start)
        if drift > 0.002:
            if player._loop_start_bytes:
                player._manager.channel_set_position_bytes(player._stream, player._loop_start_bytes)
            else:
                player._manager.channel_set_position(player._stream, player._loop_start)
            post_pos = player._manager.channel_get_seconds(player._stream)
    except Exception:
        pass
    if player._debug_loop:
        logger.debug(
            "Loop debug: jump #%s reason=%s pos=%.6f post=%.6f start=%.6f end=%.6f stream=%s",
            player._loop_iteration,
            reason,
            pos if pos is not None else -1.0,
            post_pos if post_pos is not None else -1.0,
            player._loop_start,
            player._loop_end,
            player._stream,
        )
    if not player._loop_guard_armed:
        player._loop_guard_armed = True


def fade_out(player, duration: float) -> None:
    if duration <= 0 or not player._stream:
        player.stop()
        return

    target_stream = player._stream
    start_ts = time.perf_counter()

    def _runner(target: int) -> None:
        steps = max(4, int(duration / 0.05))
        interrupted = False
        try:
            initial = player._gain_factor
            logger.debug(
                "BASS fade start stream=%s duration=%.3f gain=%.3f steps=%d",
                target,
                duration,
                initial,
                steps,
            )
            for i in range(steps):
                if player._stream != target:
                    interrupted = True
                    break
                factor = initial * (1.0 - float(i + 1) / steps)
                try:
                    player._manager.channel_set_volume(target, factor)
                except Exception as exc:
                    logger.debug("BASS fade step failed: %s", exc)
                    interrupted = True
                    break
                time.sleep(duration / steps)
        finally:
            elapsed = time.perf_counter() - start_ts
            completed = not interrupted and player._stream == target
            logger.debug(
                "BASS fade done stream=%s requested=%.3f elapsed=%.3f completed=%s",
                target,
                duration,
                elapsed,
                completed,
            )
            if interrupted or player._stream != target:
                try:
                    player._manager.channel_set_volume(target, player._gain_factor)
                except Exception:
                    pass
            else:
                finished_item_id = player._current_item_id
                player.stop(_from_fade=True)
                if player._finished_callback and finished_item_id:
                    try:
                        player._finished_callback(finished_item_id)
                    except Exception:
                        pass

    player._fade_thread = threading.Thread(target=_runner, args=(target_stream,), daemon=True)
    player._fade_thread.start()
