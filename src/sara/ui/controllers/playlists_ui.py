"""Playlist UI helpers extracted from the main frame."""

from __future__ import annotations

import wx

from sara.core.hotkeys import HotkeyAction
from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistKind, PlaylistModel
from sara.ui.folder_playlist_panel import FolderPlaylistPanel
from sara.ui.news_playlist_panel import NewsPlaylistPanel
from sara.ui.playlist_panel import PlaylistPanel


def add_playlist(frame, model: PlaylistModel) -> None:
    for action, key in frame._playlist_hotkey_defaults.items():
        model.hotkeys.setdefault(action, HotkeyAction(key=key, description=action.title()))

    saved_slots = frame._settings.get_playlist_outputs(model.name)
    if saved_slots:
        model.set_output_slots(saved_slots)

    container = wx.Panel(frame._playlist_container, style=wx.TAB_TRAVERSAL)
    container.SetName(model.name)

    header = wx.StaticText(container, label=model.name)
    header_font = header.GetFont()
    header_font.MakeBold()
    header.SetFont(header_font)
    header.SetName(model.name)
    header.Bind(wx.EVT_LEFT_DOWN, lambda event, playlist_id=model.id: frame._handle_focus_click(event, playlist_id))

    if model.kind is PlaylistKind.NEWS:
        panel = NewsPlaylistPanel(
            container,
            model=model,
            get_line_length=frame._settings.get_news_line_length,
            get_audio_devices=frame._news_device_entries,
            on_focus=frame._on_playlist_focus,
            on_play_audio=lambda path, device: frame._play_news_audio_clip(model, path, device),
            on_device_change=lambda _model=model: frame._persist_playlist_outputs(model),
            on_preview_audio=frame._preview_news_clip,
            on_stop_preview_audio=frame._stop_preview,
        )
    elif model.kind is PlaylistKind.FOLDER:
        panel = FolderPlaylistPanel(
            container,
            model=model,
            on_focus=frame._on_playlist_focus,
            on_selection_change=frame._on_playlist_selection_change,
            on_mix_configure=frame._on_mix_points_configure,
            on_preview_request=lambda playlist_id, item_id: frame._handle_folder_preview(playlist_id, item_id),
            on_send_to_music=lambda playlist_id, item_ids: frame._send_folder_items_to_music(playlist_id, item_ids),
            on_select_folder=lambda playlist_id: frame._select_folder_for_playlist(playlist_id),
            on_reload_folder=lambda playlist_id: frame._reload_folder_playlist(playlist_id),
        )
    else:
        panel = PlaylistPanel(
            container,
            model=model,
            on_focus=frame._on_playlist_focus,
            on_mix_configure=frame._on_mix_points_configure,
            on_toggle_selection=frame._on_toggle_selection,
            on_selection_change=frame._on_playlist_selection_change,
            on_play_request=frame._on_playlist_play_request,
            swap_play_select=frame._swap_play_select,
        )
    panel.SetMinSize((360, 300))

    column_sizer = wx.BoxSizer(wx.VERTICAL)
    column_sizer.Add(header, 0, wx.ALL | wx.EXPAND, 5)
    column_sizer.Add(wx.StaticLine(container), 0, wx.LEFT | wx.RIGHT, 5)
    column_sizer.Add(panel, 1, wx.EXPAND | wx.ALL, 5)
    container.SetSizer(column_sizer)
    container.SetMinSize((380, 320))

    container.Bind(wx.EVT_LEFT_DOWN, lambda event, playlist_id=model.id: frame._handle_focus_click(event, playlist_id))

    frame._playlist_sizer.Add(container, 0, wx.EXPAND | wx.ALL, 8)
    frame._playlist_container.Layout()
    frame._playlist_container.FitInside()

    frame._playlists[model.id] = panel
    frame._playlist_wrappers[model.id] = container
    frame._playlist_headers[model.id] = header
    frame._playlist_titles[model.id] = model.name
    frame._last_started_item_id.setdefault(model.id, None)
    if model.kind is PlaylistKind.FOLDER and model.folder_path:
        frame._load_folder_playlist(model, announce=False)
    frame._layout.add_playlist(model.id)
    if model.id not in frame._state.playlists:
        frame._state.add_playlist(model)
    frame._update_active_playlist_styles()
    frame._announce_event("playlist", _("Playlist %s added") % model.name)


def apply_playlist_order(frame, order: list[str]) -> None:
    applied = frame._layout.apply_order(order)
    frame._playlist_sizer.Clear(delete_windows=False)
    for playlist_id in frame._layout.state.order:
        wrapper = frame._playlist_wrappers.get(playlist_id)
        if wrapper is not None:
            frame._playlist_sizer.Add(wrapper, 0, wx.EXPAND | wx.ALL, 8)
    frame._playlist_container.Layout()
    frame._playlist_container.FitInside()
    frame._current_index = frame._layout.current_index()
    frame._update_active_playlist_styles()


def remove_playlist_by_id(frame, playlist_id: str, *, announce: bool = True) -> bool:
    panel = frame._playlists.get(playlist_id)
    if panel is None:
        return False
    frame._stop_playlist_playback(playlist_id, mark_played=False, fade_duration=0.0)
    frame._playlists.pop(playlist_id, None)
    title = frame._playlist_titles.pop(playlist_id, playlist_id)
    wrapper = frame._playlist_wrappers.pop(playlist_id, None)
    if wrapper is not None:
        wrapper.Destroy()
    header = frame._playlist_headers.pop(playlist_id, None)
    if header is not None:
        header.Destroy()
    frame._state.remove_playlist(playlist_id)
    frame._focus_lock.pop(playlist_id, None)
    frame._layout.remove_playlist(playlist_id)
    frame._playlist_titles.pop(playlist_id, None)
    frame._playlist_container.Layout()
    frame._playlist_container.FitInside()
    frame._playback.clear_playlist_entries(playlist_id)
    frame._last_started_item_id.pop(playlist_id, None)
    if frame._active_folder_preview and frame._active_folder_preview[0] == playlist_id:
        frame._stop_preview()
    if frame._last_music_playlist_id == playlist_id:
        frame._last_music_playlist_id = None
    frame._apply_playlist_order(frame._layout.state.order)
    if announce:
        frame._announce_event("playlist", _("Removed playlist %s") % title)
    return True

