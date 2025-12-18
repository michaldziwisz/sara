"""Playback flow helpers extracted from the main frame.

This module keeps the largest playback-related methods out of `MainFrame` while
preserving behaviour via thin delegating wrappers.
"""

from __future__ import annotations

import logging

import wx

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistKind
from sara.ui.controllers.playback_next_item import decide_next_item
from sara.ui.controllers.playback_panel_refresh import capture_panel_selection, refresh_preserving_selection
from sara.ui.controllers import playback_start as _playback_start
from sara.ui.playlist_panel import PlaylistPanel


logger = logging.getLogger(__name__)


def play_item_direct(frame, playlist_id: str, item_id: str, *, panel_type=PlaylistPanel) -> bool:
    panel = frame._playlists.get(playlist_id)
    playlist = frame._get_playlist_model(playlist_id)
    if not isinstance(panel, panel_type) or playlist is None:
        return False
    if frame._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC:
        return frame._auto_mix_play_next(panel)
    # Tryb ręczny: jeśli jest ustawiona kolejka (zaznaczenia), ma ona zawsze priorytet nad wskazanym/podświetlonym.
    if (
        not frame._auto_mix_enabled
        and playlist.kind is PlaylistKind.MUSIC
        and frame._playlist_has_selection(playlist_id)
    ):
        return frame._start_next_from_playlist(panel, ignore_ui_selection=True, advance_focus=False)
    item = playlist.get_item(item_id)
    if item is None:
        return False
    if start_playback(frame, panel, item, restart_playing=True):
        frame._last_started_item_id[playlist.id] = item.id
        status_message = _("Playing %s from playlist %s") % (frame._format_track_name(item), playlist.name)
        frame._announce_event("playback_events", status_message, spoken_message="")
        if frame._swap_play_select and playlist.kind is PlaylistKind.MUSIC:
            playlist.clear_selection(item.id)
            frame._refresh_selection_display(playlist.id)
        return True
    return False


def start_playback(
    frame,
    panel: PlaylistPanel,
    item: PlaylistItem,
    *,
    restart_playing: bool = False,
    auto_mix_sequence: bool = False,
    prefer_overlap: bool = False,
) -> bool:
    return _playback_start.start_playback(
        frame,
        panel,
        item,
        restart_playing=restart_playing,
        auto_mix_sequence=auto_mix_sequence,
        prefer_overlap=prefer_overlap,
    )


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
        next_idx = frame._auto_mix_tracker.next_index(playlist, break_resume_index=playlist.break_resume_index)
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
    if playlist.kind is PlaylistKind.MUSIC and playlist.break_resume_index is not None:
        break_target_index: int | None = playlist.break_resume_index
        playlist.break_resume_index = None
    else:
        break_target_index = None

    current_ctx = frame._playback.get_context(playlist.id) if restart_playing else None
    current_playing_item_id = current_ctx[0][1] if current_ctx else None

    decision = decide_next_item(
        playlist,
        panel_selected_indices=panel.get_selected_indices(),
        panel_focus_index=panel.get_focused_index(),
        ignore_ui_selection=ignore_ui_selection,
        last_started_item_id=frame._last_started_item_id.get(playlist.id),
        break_target_index=break_target_index,
        restart_playing=restart_playing,
        current_playing_item_id=current_playing_item_id,
    )
    preferred_item_id = decision.preferred_item_id
    play_index = decision.play_index
    used_ui_selection = decision.used_ui_selection
    consumed_model_selection = decision.consumed_model_selection
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
    previous_selection, previous_focus = capture_panel_selection(panel)
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
            refresh_preserving_selection(
                panel,
                previous_selection=previous_selection,
                previous_focus=previous_focus,
                item_count=len(model.items),
            )

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
