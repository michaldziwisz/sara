"""Mix trigger scheduling helpers."""

from __future__ import annotations

import logging
from typing import Any, Callable

from sara.core.playlist import PlaylistItem, PlaylistModel
from sara.ui.mix_runtime._helpers import _direct_call


logger = logging.getLogger(__name__)


def sync_loop_mix_trigger(
    frame,
    *,
    panel: Any | None,
    playlist: PlaylistModel,
    item: PlaylistItem,
    context: Any,
    call_after: Callable[..., Any] | None = None,
) -> None:
    call_after = call_after or _direct_call
    key = (playlist.id, item.id)
    if item.loop_enabled and item.has_loop():
        frame._playback.auto_mix_state[key] = "loop_hold"
        frame._playback.update_mix_trigger(
            playlist.id,
            item.id,
            mix_trigger_seconds=None,
            on_mix_trigger=None,
        )
        frame._clear_mix_plan(playlist.id, item.id)
        logger.debug("UI: loop_hold active, mix trigger cleared playlist=%s item=%s", playlist.id, item.id)
        return

    if frame._playback.auto_mix_state.get(key) == "loop_hold":
        frame._playback.auto_mix_state.pop(key, None)

    effective_override = None
    getter = getattr(context.player, "get_length_seconds", None)
    if getter:
        try:
            total_len = float(getter())
            if total_len > 0.0:
                effective_override = max(0.0, total_len - (item.cue_in_seconds or 0.0))
        except Exception:
            effective_override = None

    native_trigger = frame._supports_mix_trigger(context.player)
    mix_at, fade_seconds, base_cue, effective_duration = frame._resolve_mix_timing(
        item,
        effective_duration_override=effective_override,
    )
    if mix_at is None:
        frame._clear_mix_plan(playlist.id, item.id)
        return
    current_abs = (item.cue_in_seconds or 0.0) + (item.current_position or 0.0)
    if current_abs >= mix_at - 0.05:
        logger.debug(
            "UI: loop disabled but mix point already passed playlist=%s item=%s current=%.3f mix_at=%.3f -> no trigger",
            playlist.id,
            item.id,
            current_abs,
            mix_at,
        )
        return
    frame._register_mix_plan(
        playlist.id,
        item.id,
        mix_at=mix_at,
        fade_seconds=fade_seconds,
        base_cue=base_cue,
        effective_duration=effective_duration,
        native_trigger=native_trigger,
    )
    if native_trigger:
        frame._playback.update_mix_trigger(
            playlist.id,
            item.id,
            mix_trigger_seconds=mix_at,
            on_mix_trigger=lambda pl_id=playlist.id, it_id=item.id: call_after(
                frame._auto_mix_now_from_callback, pl_id, it_id
            ),
        )
    logger.debug(
        "UI: loop disabled -> rescheduled mix trigger playlist=%s item=%s mix_at=%.3f fade=%.3f current=%.3f native=%s",
        playlist.id,
        item.id,
        mix_at,
        fade_seconds,
        current_abs,
        native_trigger,
    )


def apply_mix_trigger_to_playback(
    frame,
    *,
    playlist_id: str,
    item: PlaylistItem,
    panel: Any,
    call_after: Callable[..., Any] | None = None,
) -> None:
    call_after = call_after or _direct_call
    if item.break_after:
        cleared = frame._playback.update_mix_trigger(
            playlist_id,
            item.id,
            mix_trigger_seconds=None,
            on_mix_trigger=None,
        )
        if cleared:
            logger.debug("UI: cleared mix trigger for break item playlist=%s item=%s", playlist_id, item.id)
        frame._clear_mix_plan(playlist_id, item.id)
        return

    ctx = frame._playback.contexts.get((playlist_id, item.id))
    effective_override = None
    if ctx:
        getter = getattr(ctx.player, "get_length_seconds", None)
        if getter:
            try:
                total_len = float(getter())
                effective_override = max(0.0, total_len - (item.cue_in_seconds or 0.0))
            except Exception:
                pass

    mix_trigger_seconds, fade_seconds, base_cue, effective_duration = frame._resolve_mix_timing(
        item,
        effective_duration_override=effective_override,
    )
    native_trigger = frame._supports_mix_trigger(ctx.player if ctx else None)
    frame._register_mix_plan(
        playlist_id,
        item.id,
        mix_at=mix_trigger_seconds,
        fade_seconds=fade_seconds,
        base_cue=base_cue,
        effective_duration=effective_duration,
        native_trigger=native_trigger,
    )
    updated = False
    if native_trigger and mix_trigger_seconds is not None:
        updated = frame._playback.update_mix_trigger(
            playlist_id,
            item.id,
            mix_trigger_seconds=mix_trigger_seconds,
            on_mix_trigger=lambda pl_id=playlist_id, it_id=item.id: call_after(
                frame._auto_mix_now_from_callback, pl_id, it_id
            ),
        )
    logger.debug(
        "UI: rescheduled mix trigger playlist=%s item=%s mix_at=%s fade=%.3f native=%s applied=%s",
        playlist_id,
        item.id,
        f"{mix_trigger_seconds:.3f}" if mix_trigger_seconds is not None else "None",
        fade_seconds,
        native_trigger,
        updated,
    )

