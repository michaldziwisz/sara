"""Playback state helpers."""

from __future__ import annotations

from sara.audio.engine import Player
from sara.core.playlist import PlaylistItemStatus, PlaylistKind
from sara.ui.playback_controller import PlaybackContext


def get_playback_context(frame, playlist_id: str) -> tuple[tuple[str, str], PlaybackContext] | None:
    return frame._playback.get_context(playlist_id)


def get_playing_item_id(frame, playlist_id: str) -> str | None:
    context = frame._get_playback_context(playlist_id)
    if context is None:
        return None
    key, _ctx = context
    return key[1]


def get_busy_device_ids(frame) -> set[str]:
    return frame._playback.get_busy_device_ids()


def stop_playlist_playback(
    frame,
    playlist_id: str,
    *,
    mark_played: bool,
    fade_duration: float = 0.0,
) -> None:
    played_tracks_logger = getattr(frame, "_played_tracks_logger", None)
    now_playing_writer = getattr(frame, "_now_playing_writer", None)
    removed_contexts = frame._playback.stop_playlist(playlist_id, fade_duration=fade_duration)
    panel = frame._playlists.get(playlist_id)
    if not panel:
        if now_playing_writer:
            for key, _context in removed_contexts:
                now_playing_writer.on_stopped(key[0], key[1])
        return
    model = panel.model
    for key, _context in removed_contexts:
        frame._clear_mix_plan(key[0], key[1])
        item_index = next((idx for idx, track in enumerate(model.items) if track.id == key[1]), None)
        item = model.items[item_index] if item_index is not None else None
        if not item:
            if now_playing_writer:
                now_playing_writer.on_stopped(key[0], key[1])
            continue
        if played_tracks_logger:
            played_tracks_logger.on_stopped(model, item, mark_played=mark_played)
        if now_playing_writer:
            now_playing_writer.on_stopped(key[0], key[1])
        if mark_played:
            if item.break_after and model.kind is PlaylistKind.MUSIC:
                target_index = (item_index + 1) if item_index is not None else None
                if target_index is not None and target_index >= len(model.items):
                    target_index = None
                model.break_resume_index = target_index
                item.break_after = False
            item.status = PlaylistItemStatus.PLAYED
            item.current_position = item.duration_seconds
        else:
            item.status = PlaylistItemStatus.PENDING
            item.current_position = 0.0
        panel.mark_item_status(item.id, item.status)
        panel.update_progress(item.id)
        panel.refresh()


def cancel_active_playback(frame, playlist_id: str, mark_played: bool = False) -> None:
    frame._stop_playlist_playback(playlist_id, mark_played=mark_played, fade_duration=0.0)


def supports_mix_trigger(frame, player: Player | None) -> bool:
    if player is None:
        return False
    try:
        return frame._playback.supports_mix_trigger(player)
    except Exception:
        return False
