"""Mix-trigger scheduling for `BassPlayer`."""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

# Keep the historical logger name for backwards-compatible filtering.
logger = logging.getLogger("sara.audio.bass.player_base")


def apply_mix_trigger(player, target_seconds: Optional[float], callback: Optional[Callable[[], None]]) -> None:
    if callback is not None and not callable(callback):
        logger.debug("BASS mix trigger: non-callable callback of type %s ignored", type(callback))
        callback = None
    player._mix_callback = callback
    # Guard against duplicate calls (pos + end fallback, or backend quirks).
    player._mix_triggered = False
    if not target_seconds or not player._stream:
        return
    original_target = float(target_seconds)
    clamped_target = original_target
    try:
        length_seconds = player._manager.channel_get_length_seconds(player._stream)
    except Exception:
        length_seconds = 0.0
    if length_seconds > 0.0 and clamped_target > (length_seconds - 0.01):
        clamped_target = max(0.0, length_seconds - 0.01)
    effective_target = clamped_target
    if player._start_offset > 0.0:
        effective_target = max(0.0, clamped_target - player._start_offset)
    try:
        target_bytes = player._manager.seconds_to_bytes(player._stream, effective_target)
    except Exception as exc:
        logger.debug("BASS mix trigger: failed to convert seconds to bytes: %s", exc)
        return

    def _invoke_once(source: str, channel: int, *, fired_pos: float | None = None) -> None:
        if getattr(player, "_mix_triggered", False):
            return
        player._mix_triggered = True
        try:
            player._last_mix_trigger_event = {
                "perf_ts": time.perf_counter(),
                "source": source,
                "stream": channel,
                "target": float(clamped_target),
                "requested": float(original_target),
                "fired_pos": float(fired_pos) if fired_pos is not None else None,
                "reported": False,
            }
        except Exception:  # pragma: no cover - defensive
            pass
        if player._mix_callback:
            try:
                player._mix_callback()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("BASS mix trigger callback error: %s", exc)
        # Ensure end fallback cannot re-fire even if callback remains set.
        player._mix_callback = None
        logger.debug(
            "BASS mix trigger fired stream=%s target=%.3f pos=%s via=%s",
            channel,
            clamped_target,
            f"{fired_pos:.3f}" if fired_pos is not None else "unknown",
            source,
        )

    def _sync_proc(hsync, channel, data, user):  # pragma: no cover - C callback
        fired_pos = None
        try:
            fired_pos = player._manager.channel_get_seconds(channel)
        except Exception:
            fired_pos = None
        _invoke_once("pos", channel, fired_pos=fired_pos)

    def _end_sync_proc(hsync, channel, data, user):  # pragma: no cover - C callback
        fired_pos = None
        try:
            fired_pos = player._manager.channel_get_seconds(channel)
        except Exception:
            fired_pos = None
        _invoke_once("end", channel, fired_pos=fired_pos)

    player._mix_sync_proc = player._manager.make_sync_proc(_sync_proc)
    player._mix_end_sync_proc = player._manager.make_sync_proc(_end_sync_proc)
    try:
        player._mix_end_sync_handle = player._manager.channel_set_sync_end(
            player._stream,
            player._mix_end_sync_proc,
        )
        player._mix_sync_handle = player._manager.channel_set_sync_pos(
            player._stream,
            target_bytes,
            player._mix_sync_proc,
            is_bytes=True,
            mix_time=True,
        )
        logger.debug(
            "BASS mix trigger set stream=%s target=%.3f effective=%.3f offset=%.3f (requested=%.3f) callback=%s",
            player._stream,
            clamped_target,
            effective_target,
            player._start_offset,
            original_target,
            "set" if callback else "none",
        )
    except Exception as exc:
        logger.debug("BASS mix trigger: failed to set sync: %s", exc)
        player._mix_sync_proc = None
        player._mix_sync_handle = 0
        player._mix_end_sync_proc = None
        player._mix_end_sync_handle = 0


def set_mix_trigger(
    player,
    mix_trigger_seconds: Optional[float],
    on_mix_trigger: Optional[Callable[[], None]],
) -> None:
    # usuń istniejący sync i ustaw nowy, jeśli podany
    if player._stream and player._mix_sync_handle:
        try:
            player._manager.channel_remove_sync(player._stream, player._mix_sync_handle)
        except Exception:
            pass
        player._mix_sync_handle = 0
        player._mix_sync_proc = None
    if player._stream and getattr(player, "_mix_end_sync_handle", 0):
        try:
            player._manager.channel_remove_sync(player._stream, player._mix_end_sync_handle)
        except Exception:
            pass
        player._mix_end_sync_handle = 0
        player._mix_end_sync_proc = None
    player._mix_triggered = False
    player._apply_mix_trigger(mix_trigger_seconds, on_mix_trigger)
