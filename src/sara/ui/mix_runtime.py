"""Mix / automix runtime logic extracted from the main frame.

The goal of this module is to keep `MainFrame` smaller and isolate mix-related
behaviour so it can be iterated on more safely.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from sara.core.mix_planner import (
    MIX_EXPLICIT_PROGRESS_GUARD,
    MIX_NATIVE_EARLY_GUARD,
    MIX_NATIVE_LATE_GUARD,
)
from sara.core.playlist import PlaylistItem, PlaylistKind, PlaylistModel


logger = logging.getLogger(__name__)

def _direct_call(callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return callback(*args, **kwargs)


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
            on_mix_trigger=lambda pl_id=playlist.id, it_id=item.id: call_after(frame._auto_mix_now_from_callback, pl_id, it_id),
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
            on_mix_trigger=lambda pl_id=playlist_id, it_id=item.id: call_after(frame._auto_mix_now_from_callback, pl_id, it_id),
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


def auto_mix_state_process(
    frame,
    panel: Any,
    item: PlaylistItem,
    context_entry: Any,
    seconds: float,
    queued_selection: bool,
) -> None:
    playlist = panel.model
    if playlist.kind is not PlaylistKind.MUSIC:
        return
    if playlist.break_resume_index is not None:
        return
    # jeśli w playliście jest aktywny break, blokuj automix
    if frame._active_break_item.get(playlist.id):
        return
    # jeśli ten utwór był oznaczony breakiem, zablokuj miks do czasu zakończenia
    key = (playlist.id, item.id)
    state = frame._playback.auto_mix_state.get(key)
    if state == "loop_hold":
        return
    if state == "break_halt":
        return
    if not frame._auto_mix_enabled and not queued_selection:
        return
    # Break zatrzymuje automix – nie miksuj w trakcie utworu z breakiem.
    if item.break_after:
        return

    plan = frame._mix_plans.get(key)
    native_trigger = plan.native_trigger if plan else frame._supports_mix_trigger(context_entry.player)
    mix_at: float | None = None
    fade_seconds = frame._fade_duration
    base_cue = item.cue_in_seconds or 0.0
    effective_duration = item.effective_duration_seconds

    if plan:
        mix_at = plan.mix_at
        fade_seconds = plan.fade_seconds
        base_cue = plan.base_cue
        effective_duration = plan.effective_duration
    else:
        mix_at, fade_seconds, base_cue, effective_duration = frame._resolve_mix_timing(item)
        frame._register_mix_plan(
            playlist.id,
            item.id,
            mix_at=mix_at,
            fade_seconds=fade_seconds,
            base_cue=base_cue,
            effective_duration=effective_duration,
            native_trigger=native_trigger,
        )
        plan = frame._mix_plans.get(key)

    release_offset = 0.0
    if plan and plan.triggered:
        return
    if mix_at is not None and native_trigger:
        track_end = base_cue + effective_duration
        headroom_after_mix = max(0.0, track_end - mix_at)
        fade_guard_source = frame._fade_duration if item.segue_seconds is not None else fade_seconds
        fade_guard = min(MIX_NATIVE_LATE_GUARD, max(0.0, fade_guard_source))
        guard_window = min(fade_guard, headroom_after_mix)
        late_guard_shortfall = max(0.0, fade_guard - guard_window)
        if late_guard_shortfall > 0.0 and guard_window > 0.0:
            release_offset = min(guard_window, late_guard_shortfall / 2.0)
        if seconds < mix_at - MIX_NATIVE_EARLY_GUARD:
            return
        if seconds < mix_at + guard_window:
            # Nie czekaj na backend kiedy zapasu jest mniej niż oczekiwany guard lub brak zapasu po miksie.
            if late_guard_shortfall <= 0.0 or seconds < mix_at - late_guard_shortfall:
                return

    already_mixing = frame._playback.auto_mix_state.get(key, False)

    elapsed = max(0.0, seconds - base_cue)
    remaining = max(0.0, effective_duration - elapsed)
    mix_remaining: float | None = None
    if mix_at is not None:
        mix_remaining = max(0.0, mix_at - seconds)

    trigger_window = max(fade_seconds, 0.0)
    if item.overlap_seconds:
        trigger_window = max(trigger_window, item.overlap_seconds)
    if item.outro_seconds:
        trigger_window = max(trigger_window, item.outro_seconds)

    remaining_target = mix_remaining if mix_remaining is not None else remaining
    fallback_guard_trigger = False
    if mix_at is not None:
        trigger_threshold = MIX_EXPLICIT_PROGRESS_GUARD
        if native_trigger and release_offset > 0.0:
            trigger_threshold = release_offset
        should_trigger = remaining_target <= trigger_threshold
        if native_trigger and release_offset > 0.0 and remaining_target <= release_offset:
            fallback_guard_trigger = True
    else:
        should_trigger = remaining_target <= max(0.1, trigger_window)
    if not should_trigger or already_mixing:
        return

    if frame._playback.auto_mix_state.get(key) in {"break_halt", "loop_hold"}:
        return
    frame._playback.auto_mix_state[key] = True
    if plan:
        plan.triggered = True
    ignore_ui_selection = frame._auto_mix_enabled and not queued_selection
    started = frame._start_next_from_playlist(
        panel,
        ignore_ui_selection=ignore_ui_selection,
        advance_focus=True,
        restart_playing=False,
        force_automix_sequence=frame._auto_mix_enabled,
        prefer_overlap=True,
    )
    if started and frame._fade_duration > 0.0:
        fade_source = max(0.0, fade_seconds)
        if fallback_guard_trigger:
            # fallback progresowy potrzebuje miękkiego wyciszenia z pełną długością fade'u
            fade_source = max(fade_source, frame._fade_duration)
        fade_duration = min(fade_source, remaining)
        logger.debug(
            "UI: automix progress fade duration=%.3f planned=%.3f remaining=%.3f guard=%s current=%.3f",
            fade_duration,
            fade_source,
            remaining,
            fallback_guard_trigger,
            seconds,
        )
        if fade_duration > 0.0:
            try:
                context_entry.player.fade_out(fade_duration)
            except Exception:
                pass
    elif plan:
        plan.triggered = False
        frame._playback.auto_mix_state.pop(key, None)


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
                _eff
                if rescheduled is not None
                else (plan.effective_duration if plan else item.effective_duration_seconds)
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
