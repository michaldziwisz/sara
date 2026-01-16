"""Playback start logic extracted from the main frame."""

from __future__ import annotations

import logging
from typing import Callable

import wx

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistKind
from sara.ui.playlist_panel import PlaylistPanel


logger = logging.getLogger(__name__)


def _call_after_if_app(func, *args) -> None:
    app = wx.GetApp()
    if app:
        wx.CallAfter(func, *args)
    else:  # defensive: allow playback controller use without wx.App
        func(*args)


def _prepare_mix_schedule(
    frame,
    *,
    playlist,
    item: PlaylistItem,
) -> tuple[float | None, float, float, float, Callable[[], None] | None]:
    base_cue: float = item.cue_in_seconds or 0.0
    effective_duration: float = item.effective_duration_seconds

    if playlist.kind is PlaylistKind.MUSIC and item.break_after:
        return None, 0.0, base_cue, effective_duration, None

    effective_override = None
    ctx = frame._playback.contexts.get((playlist.id, item.id))
    if ctx:
        getter = getattr(ctx.player, "get_length_seconds", None)
        if getter:
            try:
                total_len = float(getter())
                effective_override = max(0.0, total_len - base_cue)
                length_diff = abs(effective_override - effective_duration)
                if length_diff > 0.5:
                    logger.debug(
                        "UI: adjusting mix timing with player length playlist=%s item=%s meta_eff=%.3f real_eff=%.3f",
                        playlist.id,
                        item.id,
                        effective_duration,
                        effective_override,
                    )
            except Exception:
                pass

    mix_trigger_seconds, fade_seconds, base_cue, effective_duration = frame._resolve_mix_timing(
        item,
        effective_duration_override=effective_override,
    )
    on_mix_trigger: Callable[[], None] | None = lambda pl_id=playlist.id, it_id=item.id: _call_after_if_app(
        frame._auto_mix_now_from_callback, pl_id, it_id
    )
    return mix_trigger_seconds, fade_seconds, base_cue, effective_duration, on_mix_trigger


def start_playback(
    frame,
    panel: PlaylistPanel,
    item: PlaylistItem,
    *,
    restart_playing: bool = False,
    auto_mix_sequence: bool = False,
    prefer_overlap: bool = False,
) -> bool:
    playlist = panel.model
    key = (playlist.id, item.id)
    frame._stop_preview()

    if (
        frame._auto_mix_enabled
        and playlist.kind is PlaylistKind.MUSIC
        and not auto_mix_sequence
        and not restart_playing
    ):
        logger.debug("UI: automix ignoring manual start for item=%s", item.id)
        return False

    if auto_mix_sequence and item.status is PlaylistItemStatus.PLAYING:
        ctx = frame._playback.contexts.get(key)
        if ctx:
            try:
                if ctx.player.is_playing():
                    logger.debug("UI: automix sequence ignoring restart of already playing item=%s", item.id)
                    return True
            except Exception:
                pass

    if (
        frame._auto_mix_enabled
        and playlist.kind is PlaylistKind.MUSIC
        and item.status is PlaylistItemStatus.PLAYED
        and not restart_playing
    ):
        logger.debug("UI: automix ignoring start for PLAYED item=%s (no restart)", item.id)
        return False

    if not item.path.exists():
        item.status = PlaylistItemStatus.PENDING
        update_item = getattr(panel, "update_item_display", None)
        if callable(update_item):
            update_item(item.id)
        else:
            panel.mark_item_status(item.id, item.status)
            panel.refresh()
        frame._announce_event("playback_errors", _("File %s does not exist") % item.path)
        return False

    context = frame._playback.contexts.get(key)
    logger.debug(
        "UI: start playback request playlist=%s item=%s existing_context=%s device=%s slot=%s",
        playlist.id,
        item.id,
        bool(context),
        getattr(context, "device_id", None),
        getattr(context, "slot_index", None),
    )
    player = context.player if context else None
    device_id = context.device_id if context else None
    slot_index = context.slot_index if context else None

    if player is None or device_id is None or slot_index is None:
        existing_context = frame._get_playback_context(playlist.id)
        if existing_context:
            existing_key, _existing = existing_context
            state = frame._playback.auto_mix_state.get(existing_key)
            crossfade_active = prefer_overlap or (state is True)
            logger.debug(
                "UI: stopping existing context for playlist %s crossfade_active=%s",
                playlist.id,
                crossfade_active,
            )
            if not crossfade_active:
                fade_seconds = frame._fade_duration
                frame._stop_playlist_playback(playlist.id, mark_played=True, fade_duration=fade_seconds)

    def _on_finished(finished_item_id: str) -> None:
        _call_after_if_app(frame._handle_playback_finished, playlist.id, finished_item_id)

    def _on_progress(progress_item_id: str, seconds: float) -> None:
        _call_after_if_app(frame._handle_playback_progress, playlist.id, progress_item_id, seconds)

    start_seconds = item.cue_in_seconds or 0.0
    logger.debug("UI: invoking playback controller for item %s at %.3fs", item.id, start_seconds)

    if frame._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC and item.status is PlaylistItemStatus.PLAYED:
        logger.debug("UI: automix skip PLAYED item=%s -> force next sequence", item.id)
        total = len(playlist.items)
        if total == 0:
            return False
        next_idx = frame._auto_mix_tracker.next_index(playlist, break_resume_index=playlist.break_resume_index)
        playlist.break_resume_index = None
        logger.debug(
            "UI: automix skip PLAYED -> start idx=%s last=%s break_resume=%s",
            next_idx,
            frame._auto_mix_tracker._last_item_id.get(playlist.id),
            playlist.break_resume_index,
        )
        return frame._auto_mix_start_index(
            panel,
            next_idx,
            restart_playing=restart_playing,
            overlap_trigger=prefer_overlap,
        )

    mix_trigger_seconds, fade_seconds, base_cue, effective_duration, on_mix_trigger = _prepare_mix_schedule(
        frame,
        playlist=playlist,
        item=item,
    )

    try:
        result = frame._playback.start_item(
            playlist,
            item,
            start_seconds=start_seconds,
            on_finished=_on_finished,
            on_progress=_on_progress,
            restart_if_playing=restart_playing,
            mix_trigger_seconds=mix_trigger_seconds,
            on_mix_trigger=on_mix_trigger,
        )
        logger.debug(
            "UI: mix trigger scheduled item=%s mix_at=%s fade=%.3f cue=%.3f effective=%.3f seg=%s ovl=%s",
            item.id,
            f"{mix_trigger_seconds:.3f}" if mix_trigger_seconds is not None else "None",
            fade_seconds,
            base_cue,
            effective_duration,
            getattr(item, "segue_seconds", None),
            getattr(item, "overlap_seconds", None),
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception(
            "UI: start_item failed for playlist=%s item_id=%s title=%s err=%s",
            playlist.id,
            item.id,
            getattr(item, "title", item.id),
            exc,
        )
        return False
    if result is None:
        item.status = PlaylistItemStatus.PENDING
        update_item = getattr(panel, "update_item_display", None)
        if callable(update_item):
            update_item(item.id)
        else:
            panel.mark_item_status(item.id, item.status)
            panel.refresh()
        return False
    played_tracks_logger = getattr(frame, "_played_tracks_logger", None)
    if played_tracks_logger:
        played_tracks_logger.on_started(playlist, item)
    now_playing_writer = getattr(frame, "_now_playing_writer", None)
    if now_playing_writer:
        now_playing_writer.on_started(playlist, item)
    logger.debug(
        "UI: playback started playlist=%s item=%s device=%s slot=%s",
        playlist.id,
        item.id,
        device_id or getattr(result, "device_id", None),
        slot_index or getattr(result, "slot_index", None),
    )
    native_trigger = frame._supports_mix_trigger(result.player)
    frame._register_mix_plan(
        playlist.id,
        item.id,
        mix_at=mix_trigger_seconds,
        fade_seconds=fade_seconds,
        base_cue=base_cue,
        effective_duration=effective_duration,
        native_trigger=native_trigger,
    )
    frame._adjust_duration_and_mix_trigger(panel, playlist, item, result)
    item.status = PlaylistItemStatus.PLAYING
    update_item = getattr(panel, "update_item_display", None)
    if callable(update_item):
        update_item(item.id)
    else:
        panel.mark_item_status(item.id, PlaylistItemStatus.PLAYING)
        if frame._focus_playing_track:
            panel.refresh(focus=False)

    if frame._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC and frame._focus_playing_track:
        idx = playlist.index_of(item.id)
        if idx >= 0:
            select_index = getattr(panel, "select_index", None)
            if callable(select_index):
                select_index(idx, focus=True)
    frame._focus_lock[playlist.id] = False
    frame._last_started_item_id[playlist.id] = item.id
    if playlist.kind is PlaylistKind.MUSIC and item.break_after:
        frame._playback.auto_mix_state[(playlist.id, item.id)] = "break_halt"
        frame._active_break_item[playlist.id] = item.id
    frame._sync_loop_mix_trigger(panel=panel, playlist=playlist, item=item, context=result)
    frame._maybe_focus_playing_item(panel, item.id)
    if item.has_loop() and item.loop_enabled:
        frame._announce_event("loop", _("Loop playing"))
    if frame._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC:
        try:
            frame._playback.schedule_next_preload(playlist, current_item_id=item.id)
        except Exception:
            pass
    return True
