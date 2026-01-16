"""Loop + remaining-time actions."""

from __future__ import annotations

import logging

import wx

from sara.core.i18n import gettext as _
from sara.core.mix_planner import compute_air_duration_seconds
from sara.core.media_metadata import save_loop_metadata
from sara.core.playlist import PlaylistItem, PlaylistModel
from sara.ui.playback_controller import PlaybackContext
from sara.ui.playlist_panel import PlaylistPanel

from sara.ui.mix_runtime import sync_loop_mix_trigger as _sync_loop_mix_trigger_impl


logger = logging.getLogger(__name__)


def on_toggle_loop_playback(frame, _event: wx.CommandEvent) -> None:
    # 1) Jeśli gdziekolwiek gra pętla – wyłącz ją globalnie, niezależnie od zaznaczenia/playlisty.
    def _find_active_loop() -> tuple[PlaylistItem, PlaylistModel] | None:
        for (pl_id, item_id), _ctx in frame._playback.contexts.items():
            panel = frame._playlists.get(pl_id)
            if not isinstance(panel, PlaylistPanel):
                continue
            item = panel.model.get_item(item_id)
            if item and item.loop_enabled and item.has_loop():
                return item, panel.model
        return None

    active = _find_active_loop()
    if active:
        playing_item, playing_model = active
        playing_item.loop_enabled = False
        playing_item.loop_auto_enabled = False
        if not save_loop_metadata(
            playing_item.path,
            playing_item.loop_start_seconds,
            playing_item.loop_end_seconds,
            playing_item.loop_enabled,
            playing_item.loop_auto_enabled,
        ):
            frame._announce_event("loop", _("Failed to update loop metadata"))
        frame._apply_loop_setting_to_playback(playlist_id=playing_model.id, item_id=playing_item.id)
        frame._announce_event("loop", _("Track looping disabled"))
        remaining = frame._compute_intro_remaining(playing_item)
        if remaining is not None:
            # tylko czas, bez dodatkowych prefiksów
            frame._announce_intro_remaining(remaining, prefix_only=True)
        panel = frame._playlists.get(playing_model.id)
        current_panel = frame._get_current_music_panel()
        if isinstance(panel, PlaylistPanel):
            try:
                sel = panel.get_selected_indices()
            except Exception:
                sel = []
            panel.refresh(selected_indices=sel, focus=(current_panel is panel))
        return

    # 2) W przeciwnym razie toggle dotyczy zaznaczonego utworu.
    context = frame._get_selected_context()
    if context is None:
        frame._announce_event("playlist", _("No track selected"))
        return
    panel, model, indices = context
    idx = indices[0]
    if not (0 <= idx < len(model.items)):
        frame._announce_event("playlist", _("No track selected"))
        return
    item = model.items[idx]
    if not item.has_loop():
        frame._announce_event("loop", _("Track has no loop defined"))
        return

    item.loop_enabled = not item.loop_enabled
    item.loop_auto_enabled = item.loop_enabled
    if not save_loop_metadata(
        item.path,
        item.loop_start_seconds,
        item.loop_end_seconds,
        item.loop_enabled,
        item.loop_auto_enabled,
    ):
        frame._announce_event("loop", _("Failed to update loop metadata"))
    frame._apply_loop_setting_to_playback(playlist_id=model.id, item_id=item.id)
    state = _("enabled") if item.loop_enabled else _("disabled")
    frame._announce_event("loop", _("Track looping %s") % state)
    if not item.loop_enabled:
        remaining = frame._compute_intro_remaining(item)
        if remaining is not None:
            frame._announce_intro_remaining(remaining, prefix_only=True)
    panel.refresh(selected_indices=[idx], focus=False)


def on_loop_info(frame, _event: wx.CommandEvent) -> None:
    context = frame._get_selected_context()
    if context is None:
        return
    _panel, model, indices = context
    index = indices[0]
    if not (0 <= index < len(model.items)):
        frame._announce_event("playlist", _("No track selected"))
        return
    item = model.items[index]
    messages: list[str] = []
    if item.has_loop():
        start = item.loop_start_seconds or 0.0
        end = item.loop_end_seconds or 0.0
        state = _("active") if item.loop_enabled else _("disabled")
        messages.append(_("Loop from %.2f to %.2f seconds, looping %s") % (start, end, state))
    else:
        messages.append(_("Track has no loop defined"))

    intro = item.intro_seconds
    if intro is not None:
        cue = item.cue_in_seconds or 0.0
        intro_length = max(0.0, intro - cue)
        messages.append(_("Intro length: {seconds:.1f} seconds").format(seconds=intro_length))
    else:
        messages.append(_("Intro not defined"))

    frame._announce_event("loop", ". ".join(messages))


def on_track_remaining(frame, _event: wx.CommandEvent | None = None) -> None:
    info = frame._resolve_remaining_playback()
    if info is None:
        frame._announce_event("playback_events", _("No active playback to report remaining time"))
        return
    playlist, item, remaining = info
    total_seconds = _resolve_on_air_total_seconds(frame, playlist, item)
    if total_seconds <= 0:
        frame._announce_event("playback_events", _("Remaining time unavailable for %s") % item.title)
        return
    remaining_seconds = max(0, int(round(remaining)))
    hours, remainder = divmod(remaining_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        time_text = f"{hours:d}:{minutes:02d}:{seconds:02d}"
    else:
        time_text = f"{minutes:02d}:{seconds:02d}"
    # Najpierw czas, następnie (jeśli aktywna) informacja o pętli, potem kontekst
    parts: list[str] = [time_text]
    if item.loop_enabled and item.has_loop():
        parts.append(_("Loop enabled"))
    parts.append(_("Track: %(track)s. Playlist: %(playlist)s.") % {"track": item.title, "playlist": playlist.name})
    frame._announce_event("playback_events", " ".join(parts))


def apply_loop_setting_to_playback(frame, *, playlist_id: str | None = None, item_id: str | None = None) -> None:
    for (pl_id, item_id_key), context in list(frame._playback.contexts.items()):
        if playlist_id is not None and pl_id != playlist_id:
            continue
        if item_id is not None and item_id_key != item_id:
            continue

        playlist = frame._get_playlist_model(pl_id)
        if not playlist:
            continue
        item = playlist.get_item(item_id_key)
        if not item:
            continue
        try:
            if item.loop_enabled and item.has_loop():
                context.player.set_loop(item.loop_start_seconds, item.loop_end_seconds)
            else:
                context.player.set_loop(None, None)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Failed to synchronise playback loop: %s", exc)
        frame._sync_loop_mix_trigger(panel=frame._playlists.get(pl_id), playlist=playlist, item=item, context=context)


def sync_loop_mix_trigger(
    frame,
    *,
    panel: PlaylistPanel | None,
    playlist: PlaylistModel,
    item: PlaylistItem,
    context: PlaybackContext,
) -> None:
    _sync_loop_mix_trigger_impl(
        frame,
        panel=panel,
        playlist=playlist,
        item=item,
        context=context,
        call_after=wx.CallAfter,
    )


def resolve_remaining_playback(frame) -> tuple[PlaylistModel, PlaylistItem, float] | None:
    candidate_ids: list[str] = []
    panel = frame._get_current_music_panel()
    if panel:
        candidate_ids.append(panel.model.id)
    for playlist_id, _item_id in frame._playback.contexts.keys():
        if playlist_id not in candidate_ids:
            candidate_ids.append(playlist_id)
    for playlist_id in candidate_ids:
        panel = frame._playlists.get(playlist_id)
        if not isinstance(panel, PlaylistPanel):
            continue
        item = frame._active_playlist_item(panel.model)
        if item is None:
            continue
        total_seconds = _resolve_on_air_total_seconds(frame, panel.model, item)
        remaining = max(0.0, total_seconds - item.current_position)
        return panel.model, item, remaining
    return None


def _resolve_on_air_total_seconds(frame, playlist: PlaylistModel, item: PlaylistItem) -> float:
    if item.break_after or (item.loop_enabled and item.has_loop()):
        return max(0.0, float(item.effective_duration_seconds))

    key = (playlist.id, item.id)
    plan = getattr(frame, "_mix_plans", {}).get(key)
    if plan:
        effective = max(0.0, float(plan.effective_duration))
        mix_at = plan.mix_at
        if mix_at is None:
            return effective
        track_end = float(plan.base_cue) + effective
        if (track_end - float(mix_at)) <= 0.05:
            return effective
        return max(0.0, float(mix_at) - float(plan.base_cue))

    fade_duration = max(0.0, float(getattr(frame, "_fade_duration", 0.0) or 0.0))
    return compute_air_duration_seconds(item, fade_duration)


def active_playlist_item(frame, playlist: PlaylistModel) -> PlaylistItem | None:
    playlist_keys = [key for key in frame._playback.contexts.keys() if key[0] == playlist.id]
    if not playlist_keys:
        return None
    last_started = frame._last_started_item_id.get(playlist.id)
    if last_started:
        candidate_key = (playlist.id, last_started)
        if candidate_key in frame._playback.contexts:
            item = playlist.get_item(last_started)
            if item:
                return item
    for key in reversed(list(playlist_keys)):
        item = playlist.get_item(key[1])
        if item:
            return item
    return None
