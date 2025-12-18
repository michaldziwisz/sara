"""Playlist hotkey handler."""

from __future__ import annotations

import logging

import wx

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItemStatus, PlaylistKind


logger = logging.getLogger(__name__)


def handle_playlist_hotkey(frame, event: wx.CommandEvent) -> None:
    action = frame._action_by_id.get(event.GetId())
    if not action:
        return

    if action == "mix_points":
        context = frame._get_selected_context(kinds=(PlaylistKind.MUSIC, PlaylistKind.FOLDER))
        if context is None:
            return
        _panel, model, indices = context
        index = indices[0]
        if not (0 <= index < len(model.items)):
            frame._announce_event("playlist", _("No track selected"))
            return
        item = model.items[index]
        frame._on_mix_points_configure(model.id, item.id)
        return

    panel = frame._get_current_music_panel()
    if panel is None:
        frame._announce_event("playlist", _("Select a playlist first"))
        return

    playlist = panel.model
    if action == "play":
        if frame._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC:
            if not frame._auto_mix_play_next(panel):
                frame._announce_event("playback_events", _("No scheduled tracks available"))
        else:
            frame._start_next_from_playlist(panel)
        return
    if action == "break_toggle":
        if playlist.kind is not PlaylistKind.MUSIC:
            frame._announce_event("playlist", _("Breaks are only available on music playlists"))
            return
        indices = panel.get_selected_indices()
        if not indices:
            focus_idx = panel.get_focused_index()
            if focus_idx != wx.NOT_FOUND:
                indices = [focus_idx]
        if not indices:
            frame._announce_event("playlist", _("Select a track to toggle break"))
            return
        last_state = None
        toggled_ids: list[str] = []
        for idx in indices:
            if 0 <= idx < len(playlist.items):
                track = playlist.items[idx]
                track.break_after = not track.break_after
                last_state = track.break_after
                toggled_ids.append(track.id)
                if track.break_after:
                    frame._playback.auto_mix_state[(playlist.id, track.id)] = "break_halt"
                else:
                    frame._playback.auto_mix_state.pop((playlist.id, track.id), None)
        panel.refresh(indices, focus=True)
        if last_state is not None:
            message = _("Break enabled after track") if last_state else _("Break cleared")
            frame._announce_event("playlist", message)
        if last_state and indices:
            frame._active_break_item[playlist.id] = playlist.items[indices[0]].id
        elif not last_state:
            frame._active_break_item.pop(playlist.id, None)

        context_entry = frame._get_playback_context(playlist.id)
        if context_entry:
            key, ctx = context_entry
            if key[1] in toggled_ids:
                current_item = playlist.get_item(key[1])
                if current_item:
                    if last_state:
                        frame._clear_mix_plan(playlist.id, current_item.id)
                        frame._playback.update_mix_trigger(
                            playlist.id,
                            current_item.id,
                            mix_trigger_seconds=None,
                            on_mix_trigger=None,
                        )
                    else:
                        frame._apply_mix_trigger_to_playback(
                            playlist_id=playlist.id,
                            item=current_item,
                            panel=panel,
                        )
        return

    context_entry = frame._get_playback_context(playlist.id)
    if context_entry is None:
        frame._announce_event("playback_events", _("No active playback for this playlist"))
        return

    key, context = context_entry
    logger.debug("UI: hotkey action=%s playlist=%s current_item=%s", action, playlist.id, key[1])
    item = next((track for track in playlist.items if track.id == key[1]), None)

    if action == "pause":
        try:
            context.player.pause()
        except Exception as exc:  # pylint: disable=broad-except
            frame._announce_event("playback_errors", _("Pause error: %s") % exc)
            return
        if item:
            item.status = PlaylistItemStatus.PAUSED
            panel.mark_item_status(item.id, item.status)
            panel.refresh()
        frame._playback.contexts[key] = context
        frame._announce_event("playback_events", f"Playlista {playlist.name} wstrzymana")
    elif action == "stop":
        frame._stop_playlist_playback(playlist.id, mark_played=False, fade_duration=0.0)
        frame._announce_event("playback_events", f"Playlista {playlist.name} zatrzymana")
        frame._set_auto_mix_enabled(False, reason=_("Auto mix disabled (manual stop)"))
    elif action == "fade":
        fade_seconds = frame._manual_fade_duration(playlist, item)
        logger.debug(
            "UI: manual fade resolved duration=%.3f playlist=%s item=%s",
            fade_seconds,
            playlist.id,
            getattr(item, "id", None),
        )
        frame._stop_playlist_playback(playlist.id, mark_played=True, fade_duration=fade_seconds)
        if item:
            panel.mark_item_status(item.id, item.status)
            panel.refresh()
        frame._announce_event(
            "playback_events",
            _("Playlist %s finished track with fade out") % playlist.name,
        )
        frame._set_auto_mix_enabled(False, reason=_("Auto mix disabled (manual stop)"))
