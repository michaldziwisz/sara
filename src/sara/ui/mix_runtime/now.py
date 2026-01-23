"""Immediate / native-triggered automix flow."""

from __future__ import annotations

import logging
import time
from typing import Any

from sara.core.playlist import PlaylistItem, PlaylistKind, PlaylistModel


logger = logging.getLogger(__name__)


def auto_mix_now(frame, playlist: PlaylistModel, item: PlaylistItem, panel: Any) -> None:
    """Wyzwól miks natychmiast z precyzyjnego punktu (segue/overlap/fade sync z BASS)."""
    key = (playlist.id, item.id)
    plan = frame._mix_plans.get(key)
    if plan and plan.triggered:
        return
    queued_selection = frame._playlist_has_selection(playlist.id)
    if not frame._auto_mix_enabled and not queued_selection:
        return
    if frame._playback.auto_mix_state.get(key):
        return
    if item.break_after or frame._active_break_item.get(playlist.id) == item.id:
        frame._playback.auto_mix_state[(playlist.id, item.id)] = "break_halt"
        logger.debug(
            "UI: auto_mix_now ignored due to break playlist=%s item=%s",
            playlist.id,
            item.id,
        )
        return
    base_cue = plan.base_cue if plan else (item.cue_in_seconds or 0.0)
    length_seconds = None
    ctx = frame._playback.contexts.get(key)
    if ctx:
        getter = getattr(ctx.player, "get_length_seconds", None)
        if getter:
            try:
                length_seconds = float(getter())
            except Exception:
                length_seconds = None
    if length_seconds is None and plan:
        length_seconds = base_cue + plan.effective_duration
    max_mix_point = None
    if length_seconds and length_seconds > 0.0:
        max_mix_point = max(0.0, length_seconds - 0.01)
    expected_mix = plan.mix_at if plan else frame._mix_trigger_points.get(key)
    if expected_mix is None:
        mix_trigger, fade_seconds, base_cue, eff = frame._resolve_mix_timing(item)
        native_trigger = frame._supports_mix_trigger(ctx.player if ctx else None)
        frame._register_mix_plan(
            playlist.id,
            item.id,
            mix_at=mix_trigger,
            fade_seconds=fade_seconds,
            base_cue=base_cue,
            effective_duration=eff,
            native_trigger=native_trigger,
        )
        expected_mix = mix_trigger
        plan = frame._mix_plans.get(key)
    if expected_mix is not None and max_mix_point is not None:
        clamped_expected = min(expected_mix, max_mix_point)
        if clamped_expected != expected_mix:
            logger.debug(
                "UI: clamping mix trigger to track length playlist=%s item=%s expected=%.3f clamped=%.3f",
                playlist.id,
                item.id,
                expected_mix,
                clamped_expected,
            )
            expected_mix = clamped_expected
            frame._register_mix_plan(
                playlist.id,
                item.id,
                mix_at=clamped_expected,
                fade_seconds=plan.fade_seconds if plan else frame._fade_duration,
                base_cue=base_cue,
                effective_duration=plan.effective_duration if plan else item.effective_duration_seconds,
                native_trigger=frame._supports_mix_trigger(ctx.player if ctx else None),
            )
            plan = frame._mix_plans.get(key)
    if expected_mix is not None:
        current_abs = base_cue + (item.current_position or 0.0)
        tolerance = 0.75
        if expected_mix is not None and current_abs < expected_mix - tolerance:
            effective_override = None
            if length_seconds is not None:
                effective_override = max(0.0, length_seconds - base_cue)
            rescheduled, _fade, _base_cue, _eff = frame._resolve_mix_timing(
                item,
                effective_duration_override=effective_override,
            )
            if rescheduled is not None and max_mix_point is not None:
                rescheduled = min(rescheduled, max_mix_point)
            fallback_mix = rescheduled if rescheduled is not None else expected_mix
            fallback_fade = _fade if rescheduled is not None else (plan.fade_seconds if plan else frame._fade_duration)
            fallback_base = _base_cue if rescheduled is not None else base_cue
            fallback_eff = (
                _eff if rescheduled is not None else (plan.effective_duration if plan else item.effective_duration_seconds)
            )
            if frame._supports_mix_trigger(ctx.player if ctx else None):
                try:
                    frame._playback.update_mix_trigger(
                        playlist.id,
                        item.id,
                        mix_trigger_seconds=None,
                        on_mix_trigger=None,
                    )
                except Exception:
                    pass
            frame._register_mix_plan(
                playlist.id,
                item.id,
                mix_at=fallback_mix,
                fade_seconds=fallback_fade,
                base_cue=fallback_base,
                effective_duration=fallback_eff,
                native_trigger=False,
            )
            plan = frame._mix_plans.get(key)
            logger.debug(
                "UI: auto_mix_now backend fired early -> fallback to progress trigger playlist=%s item=%s current=%.3f expected=%.3f",
                playlist.id,
                item.id,
                current_abs,
                fallback_mix if fallback_mix is not None else -1.0,
            )
            return
    frame._playback.auto_mix_state[key] = True
    frame._mark_mix_triggered(playlist.id, item.id)
    effective_total = (
        max(0.0, (length_seconds - base_cue))
        if length_seconds is not None
        else (plan.effective_duration if plan else item.effective_duration_seconds)
    )
    remaining = max(0.0, effective_total - item.current_position)
    logger.debug(
        "UI: auto_mix_now fired playlist=%s item=%s current_pos=%.3f remaining=%.3f",
        playlist.id,
        item.id,
        item.current_position,
        remaining,
    )
    started = frame._start_next_from_playlist(
        panel,
        ignore_ui_selection=frame._auto_mix_enabled and not queued_selection,
        advance_focus=True,
        restart_playing=False,
        force_automix_sequence=frame._auto_mix_enabled,
        prefer_overlap=True,
    )
    if started and frame._fade_duration > 0.0:
        fade_target = plan.fade_seconds if plan else frame._fade_duration
        fade_duration = min(fade_target, remaining)
        logger.debug(
            "UI: auto_mix_now fade duration=%.3f planned=%.3f remaining=%.3f current=%.3f",
            fade_duration,
            fade_target,
            remaining,
            item.current_position,
        )
        ctx = frame._playback.contexts.get(key)
        if ctx and fade_duration > 0.0:
            try:
                ctx.player.fade_out(fade_duration)
            except Exception:
                pass
    else:
        # jeśli nie udało się wystartować, oczyść flagę, aby fallback mógł spróbować ponownie
        plan_obj = frame._mix_plans.get(key)
        if plan_obj:
            plan_obj.triggered = False
        frame._playback.auto_mix_state.pop(key, None)

    ctx_for_metrics = frame._playback.contexts.get(key)
    mix_event = getattr(ctx_for_metrics.player, "_last_mix_trigger_event", None) if ctx_for_metrics else None
    if isinstance(mix_event, dict) and not mix_event.get("reported"):
        try:
            fired_pos = mix_event.get("fired_pos")
            target = mix_event.get("target")
            requested = mix_event.get("requested")
            source = mix_event.get("source")
            trigger_ts = mix_event.get("perf_ts")
            now_ts = time.perf_counter()
            delay_ms = (now_ts - float(trigger_ts)) * 1000.0 if trigger_ts is not None else None
            logger.info(
                "MIX_METRIC native playlist=%s item=%s started=%s delay_ms=%s fired_pos=%s target=%s requested=%s via=%s",
                playlist.id,
                item.id,
                started,
                f"{delay_ms:.2f}" if delay_ms is not None else "?",
                f"{float(fired_pos):.3f}" if fired_pos is not None else "?",
                f"{float(target):.3f}" if target is not None else "?",
                f"{float(requested):.3f}" if requested is not None else "?",
                source or "?",
            )
        except Exception:  # pragma: no cover - metrics are best-effort
            pass
        mix_event["reported"] = True
