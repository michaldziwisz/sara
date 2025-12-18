"""Auto-mix sequencing logic extracted from the main frame."""

from __future__ import annotations

import logging

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistKind
from sara.ui.playlist_panel import PlaylistPanel


logger = logging.getLogger(__name__)

ANNOUNCEMENT_PREFIX = "\uf8ff"


def set_auto_mix_enabled(frame, enabled: bool, *, reason: str | None = None) -> None:
    if frame._auto_mix_enabled == enabled:
        return
    frame._auto_mix_enabled = enabled
    if not enabled:
        frame._playback.clear_auto_mix()
    if reason:
        frame._announce_event("auto_mix", f"{ANNOUNCEMENT_PREFIX}{reason}")
    else:
        status = _("enabled") if enabled else _("disabled")
        frame._announce_event("auto_mix", f"{ANNOUNCEMENT_PREFIX}{_('Auto mix %s') % status}")
    if enabled:
        # jeśli automix włączamy podczas odtwarzania, ustaw tracker na bieżące utwory
        for (pl_id, item_id) in list(getattr(frame._playback, "contexts", {}).keys()):
            try:
                frame._auto_mix_tracker.set_last_started(pl_id, item_id)
            except Exception:
                pass
        panel = frame._get_current_music_panel()
        if panel is not None:
            playlist = getattr(panel, "model", None)
            if playlist and frame._get_playback_context(playlist.id) is None:
                items = getattr(playlist, "items", [])
                if items:
                    target_idx = frame._preferred_auto_mix_index(panel, len(items))
                    if not frame._auto_mix_start_index(panel, target_idx, restart_playing=False):
                        frame._announce_event("playback_events", _("No scheduled tracks available"))
                else:
                    frame._announce_event("playback_events", _("No scheduled tracks available"))


def auto_mix_start_index(
    frame,
    panel: PlaylistPanel,
    idx: int,
    *,
    restart_playing: bool = False,  # kept for API compatibility
    overlap_trigger: bool = False,
) -> bool:
    """Sekwencyjny start utworu o podanym indeksie w automixie (bez patrzenia na fokus/selection)."""
    playlist = panel.model
    total = len(playlist.items)
    if total == 0:
        return False
    idx = idx % total

    current_ctx = frame._get_playback_context(playlist.id)
    if current_ctx and not overlap_trigger:
        key, _ctx = current_ctx
        playing_item = playlist.get_item(key[1])
        if playing_item:
            playing_item.is_selected = False
            playing_item.status = PlaylistItemStatus.PLAYED
            playing_item.current_position = playing_item.effective_duration_seconds
        frame._stop_playlist_playback(
            playlist.id,
            mark_played=True,
            fade_duration=max(0.0, frame._fade_duration),
        )

    next_item: PlaylistItem = playlist.items[idx]
    next_item.is_selected = False
    next_item.status = PlaylistItemStatus.PENDING
    next_item.current_position = 0.0

    logger.debug(
        "UI: automix direct start idx=%s id=%s total=%s",
        idx,
        getattr(next_item, "id", None),
        total,
    )

    # restart_playing=True pozwala ominąć blokadę „PLAYED” w automixie
    started = frame._start_playback(
        panel,
        next_item,
        restart_playing=True,
        auto_mix_sequence=True,
        prefer_overlap=overlap_trigger,
    )
    if started:
        frame._last_started_item_id[playlist.id] = next_item.id
        frame._auto_mix_tracker.set_last_started(playlist.id, next_item.id)
    return started


def auto_mix_play_next(frame, panel: PlaylistPanel) -> bool:
    """Play Next w automixie: gra kolejny utwór sekwencyjnie; break przechodzi dalej (z zawijaniem)."""
    playlist = panel.model
    if not playlist.items:
        return False

    loop_hold_keys = [
        key
        for key, state in frame._playback.auto_mix_state.items()
        if state == "loop_hold" and key[0] == playlist.id
    ]
    if loop_hold_keys:
        stopped = False
        try:
            frame._stop_playlist_playback(
                playlist.id,
                mark_played=True,
                fade_duration=max(0.0, frame._fade_duration),
            )
            stopped = True
        except Exception:
            logger.debug("UI: failed to stop loop_hold playback playlist=%s", playlist.id)
        finally:
            for key in loop_hold_keys:
                frame._playback.auto_mix_state.pop(key, None)
        if stopped:
            last_loop_item_id = loop_hold_keys[-1][1]
            frame._last_started_item_id[playlist.id] = last_loop_item_id
            try:
                frame._auto_mix_tracker.set_last_started(playlist.id, last_loop_item_id)
            except Exception:
                logger.debug(
                    "UI: failed to update auto-mix tracker after loop_hold stop playlist=%s item=%s",
                    playlist.id,
                    last_loop_item_id,
                )

    if frame._auto_mix_busy.get(playlist.id):
        logger.debug("UI: automix play_next ignored (busy) playlist=%s", playlist.id)
        return False
    frame._auto_mix_busy[playlist.id] = True
    result = False
    try:
        for track in playlist.items:
            if track.status is PlaylistItemStatus.PLAYED and track.break_after:
                track.break_after = False

        total = len(playlist.items)

        current_ctx = frame._get_playback_context(playlist.id)
        if current_ctx:
            key, _ctx = current_ctx
            playing_item = playlist.get_item(key[1])
            if playing_item and playing_item.break_after and playing_item.status is PlaylistItemStatus.PLAYING:
                idx_playing = frame._index_of_item(playlist, playing_item.id) or 0
                next_idx = (idx_playing + 1) % len(playlist.items)
                playing_item.break_after = False
                playing_item.is_selected = False
                playing_item.status = PlaylistItemStatus.PLAYED
                playing_item.current_position = playing_item.effective_duration_seconds
                playlist.break_resume_index = next_idx
                frame._active_break_item.pop(playlist.id, None)
                frame._stop_playlist_playback(
                    playlist.id,
                    mark_played=True,
                    fade_duration=max(0.0, frame._fade_duration),
                )
                frame._auto_mix_tracker.set_last_started(playlist.id, playlist.items[next_idx].id)
                result = frame._auto_mix_start_index(panel, next_idx, restart_playing=False)
                return result

        idx = frame._auto_mix_tracker.next_index(playlist, break_resume_index=playlist.break_resume_index)
        playlist.break_resume_index = None

        current_ctx = frame._get_playback_context(playlist.id)
        if current_ctx:
            key, ctx = current_ctx
            current_item_id = key[1]
            try_playing = playlist.items[idx]
            if try_playing.id == current_item_id:
                for _ in range(len(playlist.items)):
                    idx = (idx + 1) % len(playlist.items)
                    if (
                        playlist.items[idx].id != current_item_id
                        and playlist.items[idx].status is not PlaylistItemStatus.PLAYING
                    ):
                        break

        logger.debug(
            "UI: automix play_next choose idx=%s total=%s last=%s",
            idx,
            total,
            frame._auto_mix_tracker._last_item_id.get(playlist.id),
        )
        frame._auto_mix_tracker.stage_next(playlist.id, playlist.items[idx].id)
        result = frame._auto_mix_start_index(panel, idx, restart_playing=False)
        return result
    finally:
        frame._auto_mix_busy[playlist.id] = False
