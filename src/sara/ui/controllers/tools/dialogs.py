"""Tools menu dialogs."""

from __future__ import annotations

import wx

from sara.core.i18n import gettext as _, set_language
from sara.core.shortcuts import get_shortcut
from sara.ui.jingles_dialog import JinglesDialog
from sara.ui.options_dialog import OptionsDialog
from sara.ui.shortcut_editor_dialog import ShortcutEditorDialog
from sara.ui.dialogs.feedback.dialog import FeedbackDialog


def on_options(frame, _event: wx.CommandEvent) -> None:
    current_language = frame._settings.get_language()
    dialog = OptionsDialog(frame, settings=frame._settings, audio_engine=frame._audio_engine)
    if dialog.ShowModal() == wx.ID_OK:
        frame._settings.save()
        frame._fade_duration = max(frame._settings.get_playback_fade_seconds(), 0.0)
        for panel in frame._playlists.values():
            refresh = getattr(panel, "refresh", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    pass
        frame._playback.reload_pfl_device()
        frame._alternate_play_next = frame._settings.get_alternate_play_next()
        frame._swap_play_select = frame._settings.get_swap_play_select()
        frame._auto_remove_played = frame._settings.get_auto_remove_played()
        frame._focus_playing_track = frame._settings.get_focus_playing_track()
        frame._intro_alert_seconds = frame._settings.get_intro_alert_seconds()
        frame._track_end_alert_seconds = frame._settings.get_track_end_alert_seconds()
        now_playing_writer = getattr(frame, "_now_playing_writer", None)
        if now_playing_writer:
            now_playing_writer.refresh()
        frame._refresh_news_panels()
        frame._apply_swap_play_select_option()
        new_language = frame._settings.get_language()
        if new_language != current_language:
            set_language(new_language)
            wx.MessageBox(
                _("Language change will apply after restarting the application."),
                _("Information"),
                parent=frame,
            )
    dialog.Destroy()


def on_edit_shortcuts(frame, _event: wx.CommandEvent) -> None:
    dialog = ShortcutEditorDialog(frame, settings=frame._settings)
    if dialog.ShowModal() == wx.ID_OK:
        values = dialog.get_values()
        for (scope, action), shortcut in values.items():
            if get_shortcut(scope, action) is None:
                continue
            frame._settings.set_shortcut(scope, action, shortcut)
        frame._settings.save()
        frame._playlist_hotkey_defaults = frame._settings.get_playlist_shortcuts()
        frame._refresh_playlist_hotkeys()
        frame._update_shortcut_menu_labels()
        frame._configure_accelerators()
        frame._announce_event("hotkeys", _("Keyboard shortcuts saved"))
    dialog.Destroy()


def on_jingles(frame, _event: wx.CommandEvent) -> None:
    dialog = JinglesDialog(
        frame,
        audio_engine=frame._audio_engine,
        jingle_set=frame._jingles.jingle_set,
        set_path=frame._jingles_path,
        active_page_index=frame._jingles.active_page_index,
        device_id=frame._settings.get_jingles_device(),
    )
    try:
        if dialog.ShowModal() != wx.ID_OK:
            return
        result = dialog.get_result()
    finally:
        dialog.Destroy()

    frame._settings.set_jingles_device(result.device_id)
    frame._settings.save()
    frame._jingles.reload_set()
    frame._jingles.set_active_page_index(result.active_page_index)
    frame._jingles.set_device_id(result.device_id)
    frame._announce_event("jingles", frame._jingles.page_label())


def on_send_feedback(frame, _event: wx.CommandEvent) -> None:
    dialog = FeedbackDialog(frame)
    try:
        dialog.ShowModal()
    finally:
        dialog.Destroy()
