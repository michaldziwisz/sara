"""Progress-based automix trigger evaluation."""

from __future__ import annotations

import logging
from typing import Any

from sara.core.mix_planner import (
    MIX_EXPLICIT_PROGRESS_GUARD,
    MIX_NATIVE_EARLY_GUARD,
    MIX_NATIVE_LATE_GUARD,
)
from sara.core.playlist import PlaylistItem, PlaylistKind


logger = logging.getLogger(__name__)


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

