"""PFL/mix preview helpers extracted from the main frame.

This module deliberately avoids importing `wx` so it can be used in environments
where wxPython is not installed (e.g. headless CI for logic tests).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistModel


logger = logging.getLogger(__name__)


def measure_effective_duration(frame: Any, playlist: PlaylistModel, item: PlaylistItem) -> float | None:
    playback = getattr(frame, "_playback", None)
    contexts = getattr(playback, "contexts", None) if playback is not None else None
    if isinstance(contexts, dict):
        context = contexts.get((playlist.id, item.id))
        if context:
            getter = getattr(context.player, "get_length_seconds", None)
            if getter:
                try:
                    length_seconds = float(getter())
                except Exception:
                    length_seconds = None
                else:
                    if length_seconds and length_seconds > 0:
                        cue = item.cue_in_seconds or 0.0
                        return max(0.0, length_seconds - cue)

    try:
        from sara.audio.bass import BassManager  # type: ignore
    except Exception:
        return None

    stream = 0
    manager = None
    try:
        manager = BassManager.instance()
        manager.ensure_device(0)
        stream = manager.stream_create_file(0, item.path, decode=True, set_device=True)
        length_seconds = manager.channel_get_length_seconds(stream)
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Failed to probe track length via BASS for %s: %s", item.path, exc)
        return None
    finally:
        if stream and manager:
            try:
                manager.stream_free(stream)
            except Exception:
                pass

    if not length_seconds or length_seconds <= 0:
        return None
    cue = item.cue_in_seconds or 0.0
    return max(0.0, length_seconds - cue)


def preview_mix_with_next(
    frame: Any,
    playlist: PlaylistModel,
    item: PlaylistItem,
    *,
    overrides: dict[str, Optional[float]] | None = None,
) -> bool:
    """Start a short PFL preview of the mix with the next track."""
    if len(playlist.items) < 2:
        frame._announce_event("pfl", _("No next track to mix"))
        return False
    idx = frame._index_of_item(playlist, item.id)
    if idx is None:
        frame._announce_event("pfl", _("No next track to mix"))
        return False
    next_idx = (idx + 1) % len(playlist.items)
    if next_idx == idx:
        frame._announce_event("pfl", _("No next track to mix"))
        return False
    next_item = playlist.items[next_idx]

    overrides = dict(overrides or {})
    preview_pre_seconds = overrides.pop("_preview_pre_seconds", None)

    mix_plans = getattr(frame, "_mix_plans", None)
    plan = mix_plans.get((playlist.id, item.id)) if mix_plans else None
    if plan and not overrides and plan.mix_at is not None:
        mix_at = plan.mix_at
        fade_seconds = plan.fade_seconds
        base_cue = plan.base_cue
        effective_duration = plan.effective_duration
    else:
        measure = getattr(frame, "_measure_effective_duration", None)
        if callable(measure):
            effective_override = measure(playlist, item)
        else:
            effective_override = measure_effective_duration(frame, playlist, item)
        mix_at, fade_seconds, base_cue, effective_duration = frame._resolve_mix_timing(
            item,
            overrides,
            effective_duration_override=effective_override,
        )

    pre_seconds = 4.0 if preview_pre_seconds is None else max(0.0, float(preview_pre_seconds))

    ok = frame._playback.start_mix_preview(
        item,
        next_item,
        mix_at_seconds=mix_at,
        pre_seconds=pre_seconds,
        fade_seconds=fade_seconds,
        current_effective_duration=effective_duration,
        next_cue_override=next_item.cue_in_seconds or 0.0,
    )
    logger.debug(
        "UI: PFL mix preview scheduled mix_at=%s fade=%.3f cue=%.3f effective=%.3f seg=%s ovl=%s",
        f"{mix_at:.3f}" if mix_at is not None else "None",
        fade_seconds,
        base_cue,
        effective_duration,
        overrides.get("segue"),
        overrides.get("overlap"),
    )
    if not ok:
        frame._announce_event("pfl", _("No next track to mix"))
    return ok
