"""Mix planning helpers shared by UI and tests.

This module is intentionally free of wxPython dependencies so that mix timing
logic can be unit-tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass

from sara.core.playlist import PlaylistItem


MIX_NATIVE_EARLY_GUARD = 0.25
MIX_NATIVE_LATE_GUARD = 0.35
MIX_EXPLICIT_PROGRESS_GUARD = 0.05

# Okno zaufania dla natywnego wyzwalacza (mixtime). Natywny SYNC odpala dokładnie
# w punkcie miksu na osi mixtime, ale `get_position` zwraca pozycję ODTWARZANĄ —
# opóźnioną o bufor wyjściowy BASS (domyślnie 250 ms) plus jitter odpytania. Gdy
# native callback przychodzi, `current_abs` może więc legalnie być nieco przed
# `mix_at`. Okno musi być wyraźnie szersze niż bufor+jitter, żeby normalny przypadek
# ZAWSZE ufał native (powtarzalność), a na fallback progresowy schodziły tylko
# rażąco wczesne, błędne callbacki (np. zduplikat / zły sync) — patrz mix_runtime.now.
MIX_NATIVE_TRUST_WINDOW = 0.75

# Bazowy próg "siatki bezpieczeństwa" dla progresowego automixu pod natywnym
# wyzwalaczem: ścieżka progresowa nie wyzwala miksu przed punktem, dopóki nie
# wejdziemy w to okno wokół mix_at (poniżej i tak głównym źródłem jest native).
MIX_NATIVE_SAFETY_NET = MIX_NATIVE_LATE_GUARD


@dataclass
class NativeGuard:
    """Wynik wyliczenia okna strażnika dla progresowego automixu pod native.

    - `guard_window`: ile sekund PO mix_at progres czeka, zanim sam wyzwoli miks
      (siatka bezpieczeństwa, gdy native nie odpalił). Przycięte do zapasu po
      miksie, by nie przegapić końca utworu.
    - `release_offset`: dla utworów z malutkim zapasem po miksie — o ile PRZED
      mix_at progres może awaryjnie zwolnić miks, by zdążyć z fade'em.
    - `shortfall`: brakująca część pełnego guardu (gdy zapas < oczekiwany guard).
    """

    guard_window: float
    release_offset: float
    shortfall: float


def compute_native_guard(
    *,
    mix_at: float,
    base_cue: float,
    effective_duration: float,
    fade_seconds: float,
    fade_duration: float,
    has_segue: bool,
) -> NativeGuard:
    """Policz okno strażnika progresowego pod natywnym wyzwalaczem.

    Wydzielone z mix_runtime.progress, żeby logika guardu żyła w JEDNYM,
    testowalnym miejscu (bez wxPython). Zachowuje dotychczasowe zachowanie:
    pełny guard = min(MIX_NATIVE_LATE_GUARD, źródłowy fade), przycięty do zapasu
    po miksie; przy niedoborze zapasu wyznacza miękkie wcześniejsze zwolnienie.
    """
    track_end = base_cue + effective_duration
    headroom_after_mix = max(0.0, track_end - mix_at)
    fade_guard_source = fade_duration if has_segue else fade_seconds
    fade_guard = min(MIX_NATIVE_SAFETY_NET, max(0.0, fade_guard_source))
    guard_window = min(fade_guard, headroom_after_mix)
    shortfall = max(0.0, fade_guard - guard_window)
    release_offset = 0.0
    if shortfall > 0.0 and guard_window > 0.0:
        release_offset = min(guard_window, shortfall / 2.0)
    return NativeGuard(guard_window=guard_window, release_offset=release_offset, shortfall=shortfall)

MixKey = tuple[str, str]


@dataclass
class MixPlan:
    mix_at: float | None
    fade_seconds: float
    base_cue: float
    effective_duration: float
    native_trigger: bool
    triggered: bool = False


def register_mix_plan(
    mix_plans: dict[MixKey, MixPlan],
    mix_trigger_points: dict[MixKey, float],
    playlist_id: str,
    item_id: str,
    *,
    mix_at: float | None,
    fade_seconds: float,
    base_cue: float,
    effective_duration: float,
    native_trigger: bool,
) -> None:
    key = (playlist_id, item_id)
    if mix_at is None:
        clear_mix_plan(mix_plans, mix_trigger_points, playlist_id, item_id)
        return
    mix_plans[key] = MixPlan(
        mix_at=mix_at,
        fade_seconds=fade_seconds,
        base_cue=base_cue,
        effective_duration=effective_duration,
        native_trigger=native_trigger,
        triggered=False,
    )
    mix_trigger_points[key] = mix_at


def clear_mix_plan(
    mix_plans: dict[MixKey, MixPlan],
    mix_trigger_points: dict[MixKey, float],
    playlist_id: str,
    item_id: str,
) -> None:
    key = (playlist_id, item_id)
    mix_plans.pop(key, None)
    mix_trigger_points.pop(key, None)


def mark_mix_triggered(mix_plans: dict[MixKey, MixPlan], playlist_id: str, item_id: str) -> None:
    plan = mix_plans.get((playlist_id, item_id))
    if plan:
        plan.triggered = True


def resolve_mix_timing(
    item: PlaylistItem,
    fade_duration: float,
    overrides: dict[str, float | None] | None = None,
    *,
    effective_duration_override: float | None = None,
) -> tuple[float | None, float, float, float]:
    """Return (mix_at_seconds, fade_seconds, base_cue, effective_duration).

    - `mix_at_seconds` is an absolute timestamp in track seconds (including cue-in).
    - `base_cue` is the cue-in (seconds) used for calculations.
    - `effective_duration` is track duration after applying the cue-in.
    """

    overrides = dict(overrides or {})
    base_cue = overrides.get("cue")
    base_cue = base_cue if base_cue is not None else (item.cue_in_seconds or 0.0)
    effective_duration = (
        max(0.0, effective_duration_override)
        if effective_duration_override is not None
        else max(0.0, (item.duration_seconds or 0.0) - base_cue)
    )

    segue_val = overrides.get("segue")
    segue_val = segue_val if segue_val is not None else item.segue_seconds
    overlap_val = overrides.get("overlap")
    overlap_val = overlap_val if overlap_val is not None else item.overlap_seconds
    overlap_val = max(0.0, overlap_val) if overlap_val is not None else None
    segue_fade_val = overrides.get("segue_fade")
    segue_fade_val = segue_fade_val if segue_fade_val is not None else getattr(item, "segue_fade_seconds", None)
    segue_fade_val = max(0.0, segue_fade_val) if segue_fade_val is not None else None

    mix_at = None
    fade_seconds = max(0.0, float(fade_duration))
    if segue_val is not None:
        mix_at = base_cue + max(0.0, float(segue_val))
        if segue_fade_val is not None:
            fade_seconds = float(segue_fade_val)
    elif overlap_val is not None:
        mix_at = base_cue + max(0.0, effective_duration - float(overlap_val))
        fade_seconds = float(overlap_val)
    elif fade_seconds > 0.0:
        mix_at = base_cue + max(0.0, effective_duration - fade_seconds)

    if mix_at is not None:
        cap_target = base_cue + max(0.0, effective_duration - 0.01)
        if mix_at > cap_target:
            mix_at = cap_target
        remaining_after_mix = max(0.0, base_cue + effective_duration - mix_at)
        fade_seconds = min(fade_seconds, remaining_after_mix)
    return mix_at, fade_seconds, base_cue, effective_duration


def compute_mix_trigger_seconds(item: PlaylistItem, fade_duration: float) -> float | None:
    """Calculate absolute time (seconds) to trigger automix/crossfade."""
    mix_at, _, _, _ = resolve_mix_timing(item, fade_duration)
    return mix_at


def compute_air_duration_seconds(
    item: PlaylistItem,
    fade_duration: float,
    overrides: dict[str, float | None] | None = None,
    *,
    effective_duration_override: float | None = None,
    near_end_threshold: float = 0.05,
) -> float:
    """Return how long the item will play *on air* (seconds, after cue-in).

    This is the duration from cue-in to the planned mix point (segue/overlap/default fade).
    When no mix point is scheduled (e.g. fade_duration=0 and no markers), this falls back
    to the full effective duration (track end minus cue-in).

    `near_end_threshold` is used to avoid displaying the internal trigger cap (default -0.01s)
    as a shorter time when the mix point is effectively at the end of the track.
    """
    mix_at, _fade_seconds, base_cue, effective_duration = resolve_mix_timing(
        item,
        fade_duration,
        overrides,
        effective_duration_override=effective_duration_override,
    )
    effective_duration = max(0.0, float(effective_duration))
    if mix_at is None:
        return effective_duration
    track_end = base_cue + effective_duration
    if (track_end - mix_at) <= max(0.0, float(near_end_threshold)):
        return effective_duration
    return max(0.0, float(mix_at) - float(base_cue))


def mix_elapsed_seconds(mix_at: float, base_cue: float) -> float:
    """Return the mix point on the effective, post-cue timeline."""
    return max(0.0, float(mix_at) - float(base_cue))


def remaining_after_mix_seconds(mix_at: float, base_cue: float, effective_duration: float) -> float:
    """Return remaining effective playback after an absolute mix point."""
    elapsed = mix_elapsed_seconds(mix_at, base_cue)
    return max(0.0, float(effective_duration) - elapsed)


def fade_duration_at_mix(fade_seconds: float, mix_at: float, base_cue: float, effective_duration: float) -> float:
    """Clamp fade duration to the actual post-mix tail on the effective timeline."""
    return min(max(0.0, float(fade_seconds)), remaining_after_mix_seconds(mix_at, base_cue, effective_duration))
