"""Playback finish logic extracted from the main frame."""

from __future__ import annotations

import logging

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistKind
from sara.ui.controllers.playback.panel_refresh import capture_panel_selection, refresh_preserving_selection


logger = logging.getLogger(__name__)


def handle_playback_finished(frame, playlist_id: str, item_id: str) -> None:
    logger.debug("UI: playback finished callback playlist=%s item=%s", playlist_id, item_id)
    now_playing_writer = getattr(frame, "_now_playing_writer", None)
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
        if now_playing_writer:
            now_playing_writer.on_finished(playlist_id, item_id)
        return
    model = panel.model
    item_index = next((idx for idx, track in enumerate(model.items) if track.id == item_id), None)
    if item_index is None:
        if now_playing_writer:
            now_playing_writer.on_finished(playlist_id, item_id)
        return
    item = model.items[item_index]
    played_tracks_logger = getattr(frame, "_played_tracks_logger", None)
    if played_tracks_logger:
        played_tracks_logger.on_finished(model, item)

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
        if now_playing_writer:
            now_playing_writer.on_finished(playlist_id, item_id)
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
    if now_playing_writer:
        now_playing_writer.on_finished(playlist_id, item_id)
