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
from sara.ui.controllers import playback_finish as _playback_finish
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
    _playback_finish.handle_playback_finished(frame, playlist_id, item_id)
