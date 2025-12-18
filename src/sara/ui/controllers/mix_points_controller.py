"""Mix points UI controller extracted from the main frame."""

from __future__ import annotations

import wx

from sara.core.i18n import gettext as _
from sara.core.media_metadata import save_loop_metadata, save_mix_metadata
from sara.ui.dialogs.mix_point_dialog import MixPointEditorDialog


def on_mix_points_configure(frame, playlist_id: str, item_id: str) -> None:
    panel = frame._playlists.get(playlist_id)
    if panel is None:
        return
    item = next((track for track in panel.model.items if track.id == item_id), None)
    if item is None:
        return

    dialog = MixPointEditorDialog(
        frame,
        title=_("Mix points – %s") % item.title,
        duration_seconds=item.duration_seconds,
        cue_in_seconds=item.cue_in_seconds,
        intro_seconds=item.intro_seconds,
        outro_seconds=item.outro_seconds,
        segue_seconds=item.segue_seconds,
        segue_fade_seconds=item.segue_fade_seconds,
        overlap_seconds=item.overlap_seconds,
        on_preview=lambda position, loop_range=None: frame._playback.start_preview(
            item,
            max(0.0, position),
            loop_range=loop_range,
        ),
        on_mix_preview=lambda values: frame._preview_mix_with_next(panel.model, item, overrides=values),
        on_stop_preview=frame._stop_preview,
        track_path=item.path,
        initial_replay_gain=item.replay_gain_db,
        on_replay_gain_update=lambda gain, item=item: frame._apply_replay_gain(item, gain),
        loop_start_seconds=item.loop_start_seconds,
        loop_end_seconds=item.loop_end_seconds,
        loop_enabled=item.loop_enabled,
        loop_auto_enabled=item.loop_auto_enabled,
        default_fade_seconds=frame._fade_duration,
    )

    try:
        if dialog.ShowModal() != wx.ID_OK:
            return
        result = dialog.get_result()
    finally:
        dialog.Destroy()
        frame._stop_preview()

    mix_values = {
        "cue_in": result.get("cue"),
        "intro": result.get("intro"),
        "outro": result.get("outro"),
        "segue": result.get("segue"),
        "segue_fade": result.get("segue_fade"),
        "overlap": result.get("overlap"),
    }

    item.cue_in_seconds = mix_values["cue_in"]
    item.intro_seconds = mix_values["intro"]
    item.outro_seconds = mix_values["outro"]
    item.segue_seconds = mix_values["segue"]
    item.segue_fade_seconds = mix_values["segue_fade"]
    item.overlap_seconds = mix_values["overlap"]

    if not save_mix_metadata(
        item.path,
        cue_in=item.cue_in_seconds,
        intro=item.intro_seconds,
        outro=item.outro_seconds,
        segue=item.segue_seconds,
        segue_fade=item.segue_fade_seconds,
        overlap=item.overlap_seconds,
    ):
        frame._announce_event("pfl", _("Failed to update mix metadata"))
    else:
        frame._announce_event("pfl", _("Updated mix points for %s") % item.title)
        frame._propagate_mix_points_for_path(
            path=item.path,
            mix_values=mix_values,
            source_playlist_id=playlist_id,
            source_item_id=item.id,
        )

    panel.refresh()
    frame._apply_mix_trigger_to_playback(playlist_id=playlist_id, item=item, panel=panel)

    loop_info = result.get("loop") or {}
    loop_defined = bool(loop_info.get("enabled"))
    loop_start = loop_info.get("start")
    loop_end = loop_info.get("end")
    loop_auto_enabled = bool(result.get("loop_auto_enabled"))
    if loop_defined and loop_start is not None and loop_end is not None and loop_end > loop_start:
        try:
            item.set_loop(loop_start, loop_end)
        except ValueError as exc:
            frame._announce_event("loop", str(exc))
        else:
            item.loop_auto_enabled = loop_auto_enabled
            item.loop_enabled = loop_auto_enabled or item.loop_enabled
            if not save_loop_metadata(
                item.path,
                loop_start,
                loop_end,
                item.loop_enabled,
                item.loop_auto_enabled,
            ):
                frame._announce_event("loop", _("Failed to update loop metadata"))
            frame._apply_loop_setting_to_playback(playlist_id=playlist_id, item_id=item.id)
            panel.refresh()
    else:
        if item.has_loop() or item.loop_enabled:
            item.clear_loop()
            item.loop_auto_enabled = False
            save_loop_metadata(item.path, None, None, auto_enabled=False)
            frame._apply_loop_setting_to_playback(playlist_id=playlist_id, item_id=item.id)
            panel.refresh()

