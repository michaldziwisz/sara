"""Playback navigation/progress helpers extracted from the main frame."""

from __future__ import annotations

import logging

import wx

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistKind, PlaylistModel


logger = logging.getLogger(__name__)


def derive_next_play_index(frame, playlist: PlaylistModel) -> int | None:
    if not playlist.items:
        return None
    last_id = frame._last_started_item_id.get(playlist.id)
    if not last_id:
        return 0
    last_index = frame._index_of_item(playlist, last_id)
    if last_index is None:
        return 0
    return (last_index + 1) % len(playlist.items)


def index_of_item(playlist: PlaylistModel, item_id: str | None) -> int | None:
    if not item_id:
        return None
    for idx, entry in enumerate(playlist.items):
        if entry.id == item_id:
            return idx
    return None


def play_next_alternate(frame) -> bool:
    ordered_ids = [playlist_id for playlist_id in frame._layout.state.order if playlist_id in frame._playlists]
    if not ordered_ids:
        return False

    page_count = len(ordered_ids)
    start_index = frame._current_index % page_count
    rotated_order = [ordered_ids[(start_index + offset) % page_count] for offset in range(page_count)]

    for playlist_id in rotated_order:
        panel = frame._playlists.get(playlist_id)
        if panel is None:
            continue
        if frame._start_next_from_playlist(panel):
            try:
                index = ordered_ids.index(playlist_id)
            except ValueError:
                index = 0
            frame._current_index = (index + 1) % page_count
            frame._layout.set_current(playlist_id)
            frame._update_active_playlist_styles()
            frame._announce_event("playlist", f"Aktywna playlista {panel.model.name}")
            return True

    return False


def on_global_play_next(frame, _event: wx.CommandEvent) -> None:
    if not frame._playlists:
        frame._announce_event("playlist", _("No playlists available"))
        return

    panel, focus = frame._active_news_panel()
    if panel:
        if panel.activate_toolbar_control(focus):
            return
        if panel.consume_space_shortcut():
            return
        if panel.is_edit_control(focus):
            return
        return

    if frame._alternate_play_next:
        if not frame._play_next_alternate():
            frame._announce_event("playback_events", _("No scheduled tracks available"))
        return

    panel = frame._get_current_music_panel()
    if panel is None:
        frame._announce_event("playlist", _("Select a playlist first"))
        return

    # Automix: Play Next zawsze gra kolejny pending w kolejności; break zatrzymuje i wybieramy pending za ostatnim PLAYED.
    if frame._auto_mix_enabled and panel.model.kind is PlaylistKind.MUSIC:
        if frame._auto_mix_play_next(panel):
            return
        frame._announce_event("playback_events", _("No scheduled tracks available"))
        return

    if not frame._start_next_from_playlist(panel):
        frame._announce_event("playback_events", _("No scheduled tracks available"))


def handle_playback_progress(frame, playlist_id: str, item_id: str, seconds: float) -> None:
    context_entry = frame._playback.contexts.get((playlist_id, item_id))
    if not context_entry:
        return
    panel = frame._playlists.get(playlist_id)
    if not panel:
        return
    # automix: ignoruj wczesne wyzwalanie z powodu UI selection – sekwencją zarządza tracker
    if frame._auto_mix_enabled and panel.model.kind is PlaylistKind.MUSIC:
        queued_selection = False
    item = next((track for track in panel.model.items if track.id == item_id), None)
    if not item:
        return
    item.update_progress(seconds)
    panel.update_progress(item_id)
    frame._maybe_focus_playing_item(panel, item_id)
    frame._consider_intro_alert(panel, item, context_entry, seconds)
    frame._consider_track_end_alert(panel, item, context_entry)

    queued_selection = frame._playlist_has_selection(playlist_id)
    if frame._auto_mix_enabled or queued_selection:
        frame._auto_mix_state_process(panel, item, context_entry, seconds, queued_selection)


def manual_fade_duration(frame, playlist: PlaylistModel, item: PlaylistItem | None) -> float:
    fade_seconds = max(0.0, frame._fade_duration)
    if item is None:
        return fade_seconds
    plans = getattr(frame, "_mix_plans", {}) or {}
    plan = plans.get((playlist.id, item.id))
    effective_duration = None
    if plan:
        fade_seconds = max(0.0, plan.fade_seconds)
        effective_duration = plan.effective_duration
    else:
        effective_override = frame._measure_effective_duration(playlist, item)
        _mix_at, resolved_fade, _base_cue, effective_duration = frame._resolve_mix_timing(
            item,
            effective_duration_override=effective_override,
        )
        fade_seconds = max(0.0, resolved_fade)
    if effective_duration is None:
        effective_duration = item.effective_duration_seconds
    if effective_duration is not None:
        current_pos = getattr(item, "current_position", 0.0) or 0.0
        current_pos = max(0.0, current_pos)
        remaining = max(0.0, effective_duration - current_pos)
        fade_seconds = min(fade_seconds, remaining)
    return fade_seconds


def adjust_duration_and_mix_trigger(
    frame,
    panel,
    playlist: PlaylistModel,
    item: PlaylistItem,
    context,
) -> None:
    getter = getattr(context.player, "get_length_seconds", None)
    if not getter:
        return
    try:
        length_seconds = float(getter())
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("UI: failed to read track length from player: %s", exc)
        return
    if length_seconds <= 0:
        return
    cue = item.cue_in_seconds or 0.0
    effective_actual = max(0.0, length_seconds - cue)
    effective_meta = item.effective_duration_seconds
    if abs(effective_actual - effective_meta) <= 0.5:
        return
    item.duration_seconds = cue + effective_actual
    item.current_position = min(item.current_position, effective_actual)
    logger.debug(
        "UI: adjusted duration from player playlist=%s item=%s effective_meta=%.3f effective_real=%.3f cue=%.3f",
        playlist.id,
        item.id,
        effective_meta,
        effective_actual,
        cue,
    )
    if not item.break_after and not (item.loop_enabled and item.has_loop()):
        frame._apply_mix_trigger_to_playback(playlist_id=playlist.id, item=item, panel=panel)
