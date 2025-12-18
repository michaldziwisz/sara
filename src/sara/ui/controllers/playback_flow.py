"""Playback flow helpers extracted from the main frame.

This module keeps the largest playback-related methods out of `MainFrame` while
preserving behaviour via thin delegating wrappers.
"""

from __future__ import annotations

import logging
from typing import Callable

import wx

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistKind
from sara.ui.nvda_sleep import notify_nvda_play_next
from sara.ui.playlist_panel import PlaylistPanel


logger = logging.getLogger(__name__)


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
        app = wx.GetApp()
        if app:
            wx.CallAfter(frame._handle_playback_finished, playlist.id, finished_item_id)
        else:  # defensive: allow playback controller use without wx.App
            frame._handle_playback_finished(playlist.id, finished_item_id)

    def _on_progress(progress_item_id: str, seconds: float) -> None:
        app = wx.GetApp()
        if app:
            wx.CallAfter(frame._handle_playback_progress, playlist.id, progress_item_id, seconds)
        else:
            frame._handle_playback_progress(playlist.id, progress_item_id, seconds)

    start_seconds = item.cue_in_seconds or 0.0
    logger.debug("UI: invoking playback controller for item %s at %.3fs", item.id, start_seconds)

    try:
        notify_nvda_play_next()
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("NVDA play-next notify failed: %s", exc)

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

    mix_trigger_seconds: float | None
    fade_seconds: float = 0.0
    base_cue: float = item.cue_in_seconds or 0.0
    effective_duration: float = item.effective_duration_seconds

    if playlist.kind is PlaylistKind.MUSIC and item.break_after:
        mix_trigger_seconds = None
        on_mix_trigger: Callable[[], None] | None = None
    else:
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
        on_mix_trigger = lambda pl_id=playlist.id, it_id=item.id: wx.CallAfter(
            frame._auto_mix_now_from_callback, pl_id, it_id
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
        panel.mark_item_status(item.id, item.status)
        panel.refresh()
        return False
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

    previous_selection = panel.get_selected_indices()
    previous_focus = panel.get_focused_index()

    panel.mark_item_status(item.id, PlaylistItemStatus.PLAYING)
    if frame._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC and frame._focus_playing_track:
        idx = playlist.index_of(item.id)
        if idx >= 0:
            panel.refresh(selected_indices=[idx], focus=True)
        else:
            panel.refresh(focus=False)
    else:
        if frame._focus_playing_track:
            panel.refresh(focus=False)
        else:
            if previous_selection:
                panel.refresh(selected_indices=previous_selection, focus=True)
            elif previous_focus != wx.NOT_FOUND and 0 <= previous_focus < len(playlist.items):
                panel.refresh(focus=False)
                panel.select_index(previous_focus, focus=True)
            else:
                panel.refresh(focus=False)
    frame._focus_lock[playlist.id] = False
    frame._last_started_item_id[playlist.id] = item.id
    if playlist.kind is PlaylistKind.MUSIC and item.break_after:
        frame._playback.auto_mix_state[(playlist.id, item.id)] = "break_halt"
        frame._active_break_item[playlist.id] = item.id
    frame._sync_loop_mix_trigger(panel=panel, playlist=playlist, item=item, context=result)
    frame._maybe_focus_playing_item(panel, item.id)
    if item.has_loop() and item.loop_enabled:
        frame._announce_event("loop", _("Loop playing"))
    return True


def start_next_from_playlist(
    frame,
    panel: PlaylistPanel,
    *,
    ignore_ui_selection: bool = False,
    advance_focus: bool = True,
    restart_playing: bool = False,
    force_automix_sequence: bool = False,
    prefer_overlap: bool = False,
) -> bool:
    playlist = panel.model
    if not playlist.items:
        frame._announce_event("playlist", _("Playlist %s is empty") % playlist.name)
        return False

    if (
        frame._auto_mix_enabled
        and playlist.kind is PlaylistKind.MUSIC
        and not force_automix_sequence
        and not ignore_ui_selection
    ):
        return frame._auto_mix_play_next(panel)

    if force_automix_sequence and frame._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC:
        total = len(playlist.items)
        if total == 0:
            return False

        current_ctx = frame._get_playback_context(playlist.id)
        current_idx = None
        if current_ctx:
            current_idx = frame._index_of_item(playlist, current_ctx[0][1])

        if total == 1:
            if current_ctx:
                return True
            next_idx = 0
        elif current_idx is not None and current_idx >= 0:
            next_idx = (current_idx + 1) % total
        else:
            next_idx = frame._auto_mix_tracker.next_index(playlist, break_resume_index=playlist.break_resume_index)
        playlist.break_resume_index = None

        logger.debug(
            "UI: automix sequence -> idx=%s id=%s total=%s last=%s",
            next_idx,
            getattr(playlist.items[next_idx], "id", None),
            total,
            frame._auto_mix_tracker._last_item_id.get(playlist.id),
        )
        frame._auto_mix_tracker.stage_next(playlist.id, playlist.items[next_idx].id)

        current_ctx = frame._get_playback_context(playlist.id)
        if (
            current_ctx
            and current_ctx[0][1] == playlist.items[next_idx].id
            and playlist.items[next_idx].status is PlaylistItemStatus.PLAYING
        ):
            next_idx = (next_idx + 1) % total
            logger.debug(
                "UI: automix sequence skipping current playing item, advancing to idx=%s id=%s",
                next_idx,
                getattr(playlist.items[next_idx], "id", None),
            )
            if playlist.items[next_idx].status is PlaylistItemStatus.PLAYING:
                logger.debug("UI: automix sequence found no non-playing item to start; aborting mix")
                return True

        return frame._auto_mix_start_index(
            panel,
            next_idx,
            restart_playing=restart_playing,
            overlap_trigger=prefer_overlap,
        )

    if frame._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC:
        current_ctx = frame._get_playback_context(playlist.id)
        if current_ctx:
            key, _ctx = current_ctx
            playing_item = playlist.get_item(key[1])
            if playing_item and playing_item.break_after and playing_item.status is PlaylistItemStatus.PLAYING:
                idx_playing = frame._index_of_item(playlist, playing_item.id) or -1
                next_idx = (idx_playing + 1) % len(playlist.items)
                playing_item.break_after = False
                playing_item.is_selected = False
                playing_item.status = PlaylistItemStatus.PLAYED
                playing_item.current_position = playing_item.effective_duration_seconds
                panel.refresh(focus=False)
                frame._stop_playlist_playback(
                    playlist.id,
                    mark_played=True,
                    fade_duration=max(0.0, frame._fade_duration),
                )
                frame._auto_mix_tracker.set_last_started(playlist.id, playlist.items[next_idx].id)
        return frame._auto_mix_start_index(
            panel,
            next_idx,
            restart_playing=False,
            overlap_trigger=prefer_overlap,
        )

    consumed_model_selection = False
    preferred_item_id = playlist.next_selected_item_id()
    play_index: int | None = None

    used_ui_selection = False
    break_target_index: int | None = None
    if playlist.kind is PlaylistKind.MUSIC and playlist.break_resume_index is not None:
        break_target_index = playlist.break_resume_index
        playlist.break_resume_index = None

    if preferred_item_id:
        consumed_model_selection = True
        play_index = frame._index_of_item(playlist, preferred_item_id)
    else:
        if break_target_index is not None:
            play_index = next(
                (
                    idx
                    for idx in range(break_target_index, len(playlist.items))
                    if playlist.items[idx].status is PlaylistItemStatus.PENDING
                ),
                None,
            )
        if play_index is None and playlist.kind is PlaylistKind.MUSIC:
            last_id = frame._last_started_item_id.get(playlist.id)
            if last_id:
                last_idx = frame._index_of_item(playlist, last_id)
                last_item = playlist.get_item(last_id)
                if last_idx is not None and last_item and last_item.status is PlaylistItemStatus.PLAYED:
                    play_index = next(
                        (
                            idx
                            for idx in range(last_idx + 1, len(playlist.items))
                            if playlist.items[idx].status is PlaylistItemStatus.PENDING
                        ),
                        None,
                    )
        if play_index is None:
            if not ignore_ui_selection:
                selected_indices = [
                    idx
                    for idx in panel.get_selected_indices()
                    if 0 <= idx < len(playlist.items)
                    and playlist.items[idx].status in (PlaylistItemStatus.PENDING, PlaylistItemStatus.PAUSED)
                ]
            else:
                selected_indices = []
            if selected_indices:
                play_index = selected_indices[0]
                used_ui_selection = True
            elif not ignore_ui_selection:
                focus_index = panel.get_focused_index()
                if focus_index != wx.NOT_FOUND and 0 <= focus_index < len(playlist.items):
                    focus_item = playlist.items[focus_index]
                    if focus_item.status in (PlaylistItemStatus.PENDING, PlaylistItemStatus.PAUSED):
                        play_index = focus_index
                        used_ui_selection = True
                    else:
                        play_index = frame._derive_next_play_index(playlist)
                else:
                    play_index = frame._derive_next_play_index(playlist)
            else:
                play_index = frame._derive_next_play_index(playlist)
        if play_index is not None and 0 <= play_index < len(playlist.items):
            preferred_item_id = playlist.items[play_index].id
        else:
            preferred_item_id = None

    if play_index is not None:

        def _next_pending(start_idx: int) -> int | None:
            for idx in range(start_idx, len(playlist.items)):
                if playlist.items[idx].status in (PlaylistItemStatus.PENDING, PlaylistItemStatus.PAUSED):
                    return idx
            return None

        if not (
            0 <= play_index < len(playlist.items)
            and playlist.items[play_index].status in (PlaylistItemStatus.PENDING, PlaylistItemStatus.PAUSED)
        ):
            play_index = _next_pending((play_index + 1) if play_index is not None else 0)
            preferred_item_id = playlist.items[play_index].id if play_index is not None else None
    logger.debug(
        "UI: start_next playlist=%s preferred=%s play_index=%s used_ui=%s consumed_selection=%s ignore_ui=%s",
        playlist.id,
        preferred_item_id,
        play_index,
        used_ui_selection,
        consumed_model_selection,
        ignore_ui_selection,
    )

    if restart_playing:
        current_ctx = frame._playback.get_context(playlist.id)
        if current_ctx and preferred_item_id == current_ctx[0][1]:
            logger.debug(
                "UI: auto-mix avoiding restart of current item=%s, picking next pending",
                preferred_item_id,
            )
            play_index = frame._derive_next_play_index(playlist)
            preferred_item_id = playlist.items[play_index].id if play_index is not None else None
            consumed_model_selection = False

    if not frame._auto_mix_enabled and preferred_item_id:
        preferred_item = playlist.get_item(preferred_item_id)
        if preferred_item and preferred_item.status is PlaylistItemStatus.PLAYED:
            preferred_item.status = PlaylistItemStatus.PENDING
            preferred_item.current_position = 0.0

    item = playlist.begin_next_item(preferred_item_id)
    if not item:
        frame._announce_event("playback_events", _("No scheduled tracks in playlist %s") % playlist.name)
        return False

    current_ctx = frame._playback.get_context(playlist.id)
    if (
        current_ctx
        and current_ctx[0][1] == item.id
        and item.status is PlaylistItemStatus.PLAYING
        and not restart_playing
    ):
        logger.debug(
            "UI: item %s already playing on playlist %s and restart_playing=False -> skipping new start",
            item.id,
            playlist.id,
        )
        return True

    if frame._start_playback(panel, item, restart_playing=restart_playing):
        frame._last_started_item_id[playlist.id] = item.id
        if playlist.kind is PlaylistKind.MUSIC and frame._auto_mix_enabled:
            frame._auto_mix_tracker.set_last_started(playlist.id, item.id)
        track_name = frame._format_track_name(item)
        if item.is_selected:
            logger.debug("UI: clearing queued selection for started item=%s playlist=%s", item.id, playlist.id)
            playlist.clear_selection(item.id)
            frame._refresh_selection_display(playlist.id)
        if advance_focus and not consumed_model_selection and not used_ui_selection:
            if frame._focus_playing_track:
                next_focus = frame._derive_next_play_index(playlist)
                if next_focus is not None and 0 <= next_focus < len(playlist.items):
                    panel.select_index(next_focus, focus=False)
        status_message = _("Playing %s from playlist %s") % (track_name, playlist.name)
        frame._announce_event(
            "playback_events",
            status_message,
            spoken_message="",
        )
        return True
    return False


def handle_playback_finished(frame, playlist_id: str, item_id: str) -> None:
    logger.debug("UI: playback finished callback playlist=%s item=%s", playlist_id, item_id)
    frame._playback.auto_mix_state.pop((playlist_id, item_id), None)
    frame._clear_mix_plan(playlist_id, item_id)
    context = frame._playback.contexts.pop((playlist_id, item_id), None)
    if context:
        try:
            context.player.set_finished_callback(None)
            context.player.set_progress_callback(None)
        except Exception:
            pass
    panel = frame._playlists.get(playlist_id)
    if not panel:
        return
    model = panel.model
    item_index = next((idx for idx, track in enumerate(model.items) if track.id == item_id), None)
    if item_index is None:
        return
    item = model.items[item_index]

    removed = False
    previous_selection = panel.get_selected_indices()
    previous_focus = panel.get_focused_index()
    if frame._auto_remove_played:
        removed_item = frame._remove_item_from_playlist(panel, model, item_index, refocus=True)
        frame._announce_event("playback_events", _("Removed played track %s") % removed_item.title)
        removed = True
    else:
        model.mark_played(item_id)
        panel.mark_item_status(item_id, item.status)
        if frame._focus_playing_track:
            panel.refresh(focus=False)
        else:
            if previous_selection:
                panel.refresh(selected_indices=previous_selection, focus=True)
            elif previous_focus != wx.NOT_FOUND and 0 <= previous_focus < len(model.items):
                panel.refresh(focus=False)
                panel.select_index(previous_focus, focus=True)
            else:
                panel.refresh(focus=False)

    if context:
        try:
            context.player.stop()
        except Exception as exc:  # pylint: disable=broad-except
            frame._announce_event("playback_errors", _("Player stop error: %s") % exc)
    break_flag = (
        model.kind is PlaylistKind.MUSIC
        and (
            model.break_resume_index is not None
            or item.break_after
            or frame._active_break_item.get(playlist_id) == item_id
        )
    )
    logger.debug(
        "UI: finished item=%s break_flag=%s break_after=%s break_resume=%s active_break=%s",
        item_id,
        break_flag,
        item.break_after,
        model.break_resume_index,
        frame._active_break_item.get(playlist_id),
    )
    if not removed:
        frame._announce_event("playback_events", _("Finished %s") % item.title)

    if break_flag:
        if model.items:
            target_index = (item_index + 1) % len(model.items)
        else:
            target_index = None
        model.break_resume_index = target_index
        item.break_after = False
        frame._playback.auto_mix_state.pop((playlist_id, item_id), None)
        frame._active_break_item.pop(playlist_id, None)
        frame._auto_mix_tracker.set_last_started(playlist_id, item_id)
        return
    if frame._auto_mix_enabled and model.kind is PlaylistKind.MUSIC and model.items:
        frame._auto_mix_tracker.set_last_started(playlist_id, item_id)
        if frame._get_playback_context(playlist_id) is None:
            try:
                frame._auto_mix_play_next(panel)
            except Exception:
                logger.exception("UI: auto fallback after finish failed playlist=%s", playlist_id)
    if (
        not frame._auto_mix_enabled
        and model.kind is PlaylistKind.MUSIC
        and frame._get_playback_context(playlist_id) is None
        and frame._playlist_has_selection(playlist_id)
    ):
        try:
            frame._start_next_from_playlist(panel, ignore_ui_selection=True, advance_focus=False)
        except Exception:
            logger.exception("UI: manual queued fallback after finish failed playlist=%s", playlist_id)

