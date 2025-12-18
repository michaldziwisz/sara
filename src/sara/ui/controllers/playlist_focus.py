"""Playlist focus/selection helpers extracted from the main frame."""

from __future__ import annotations

import wx

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistKind
from sara.ui.news_playlist_panel import NewsPlaylistPanel
from sara.ui.playlist_panel import PlaylistPanel


ANNOUNCEMENT_PREFIX = "\uf8ff"


def refresh_news_panels(frame) -> None:
    for panel in frame._playlists.values():
        if isinstance(panel, NewsPlaylistPanel):
            panel.refresh_configuration()


def active_news_panel(frame) -> tuple[NewsPlaylistPanel | None, wx.Window | None]:
    focus = wx.Window.FindFocus()
    if focus is None:
        return None, None
    for panel in frame._playlists.values():
        if isinstance(panel, NewsPlaylistPanel) and panel.contains_window(focus):
            return panel, focus
    return None, focus


def focused_playlist_id(frame) -> str | None:
    focus = wx.Window.FindFocus()
    if focus is None:
        return None
    for playlist_id, wrapper in frame._playlist_wrappers.items():
        current = focus
        while current:
            if current is wrapper:
                return playlist_id
            current = current.GetParent()
    return None


def focus_playlist_panel(frame, playlist_id: str) -> bool:
    panel = frame._playlists.get(playlist_id)
    if panel is None:
        return False
    if isinstance(panel, NewsPlaylistPanel):
        panel.focus_default()
    elif isinstance(panel, PlaylistPanel):
        panel.focus_list()
    else:
        return False
    frame._on_playlist_focus(playlist_id)
    return True


def cycle_playlist_focus(frame, *, backwards: bool) -> bool:
    order = [playlist_id for playlist_id in frame._layout.state.order if playlist_id in frame._playlists]
    if not order:
        frame._announce_event("playlist", _("No playlists available"))
        return False
    current_id = frame._focused_playlist_id()
    if current_id in order:
        current_index = order.index(current_id)
        next_index = (current_index - 1) if backwards else (current_index + 1)
    else:
        next_index = len(order) - 1 if backwards else 0
    target_id = order[next_index % len(order)]
    return frame._focus_playlist_panel(target_id)


def on_playlist_selection_change(frame, playlist_id: str, indices: list[int]) -> None:
    panel = frame._playlists.get(playlist_id)
    if not isinstance(panel, PlaylistPanel):
        return
    # pobierz aktualne zaznaczenia z kontrolki (lista zdarzenia bywa opóźniona)
    indices = panel.get_selected_indices()
    playing_id = frame._get_playing_item_id(playlist_id)
    loop_active = False
    focus_idx = panel.get_focused_index()
    if focus_idx != wx.NOT_FOUND and 0 <= focus_idx < len(panel.model.items):
        sel_item = panel.model.items[focus_idx]
        loop_active = sel_item.has_loop() and (sel_item.loop_enabled or getattr(sel_item, "loop_auto_enabled", False))
    elif indices:
        idx0 = indices[0]
        if 0 <= idx0 < len(panel.model.items):
            sel_item = panel.model.items[idx0]
            loop_active = sel_item.has_loop() and (sel_item.loop_enabled or getattr(sel_item, "loop_auto_enabled", False))

    # focus-lock logika jak wcześniej
    if frame._focus_playing_track:
        if playing_id is None or not indices:
            frame._focus_lock[playlist_id] = False
        elif len(indices) == 1:
            selected_index = indices[0]
            if 0 <= selected_index < len(panel.model.items):
                selected_item = panel.model.items[selected_index]
                if selected_item.id == playing_id:
                    frame._focus_lock[playlist_id] = False
                    # nie uciekaj wcześniej – pozwól ogłosić pętlę
                    if loop_active:
                        frame._announce_event("selection", _("Loop enabled"))
                    return
            frame._focus_lock[playlist_id] = True

    # komunikat o zaznaczeniu z informacją o pętli/auto-mix
    # komunikat o pętli przy pojedynczym zaznaczeniu
    if len(indices) == 1:
        idx = indices[0]
        if 0 <= idx < len(panel.model.items):
            _item = panel.model.items[idx]
            focus_idx = panel.get_focused_index()
            if focus_idx != wx.NOT_FOUND:
                frame._last_focus_index[playlist_id] = focus_idx
            elif idx is not None:
                frame._last_focus_index[playlist_id] = idx
    # komunikat o pętli obsługuje teraz sam wiersz (prefiks „Loop” w tytule/statusie)


def on_toggle_selection(frame, playlist_id: str, item_id: str) -> None:
    if frame._auto_mix_enabled:
        frame._announce_event("selection", _("Disable auto mix to queue specific tracks"))
        return
    playlist = frame._get_playlist_model(playlist_id)
    if not playlist:
        return
    selected = playlist.toggle_selection(item_id)
    panel = frame._playlists.get(playlist_id)
    if isinstance(panel, PlaylistPanel):
        try:
            index = next(idx for idx, track in enumerate(panel.model.items) if track.id == item_id)
        except StopIteration:
            indices = None
        else:
            indices = [index]
        panel.refresh(indices, focus=bool(indices))
    item = playlist.get_item(item_id)
    if not selected and item is not None:
        frame._announce_event("selection", _("Selection removed from %s") % item.title)


def get_current_playlist_panel(frame):
    current_id = frame._layout.state.current_id
    if current_id and current_id in frame._playlists:
        return frame._playlists[current_id]

    for playlist_id in frame._layout.state.order:
        panel = frame._playlists.get(playlist_id)
        if panel:
            frame._layout.set_current(playlist_id)
            frame._current_index = frame._layout.current_index()
            frame._update_active_playlist_styles()
            frame._announce_event("playlist", f"{ANNOUNCEMENT_PREFIX}{panel.model.name}")
            return panel
    return None


def handle_focus_click(frame, event: wx.MouseEvent, playlist_id: str) -> None:
    frame._focus_playlist_panel(playlist_id)
    event.Skip()


def on_playlist_focus(frame, playlist_id: str) -> None:
    if playlist_id not in frame._playlists:
        return
    current_id = frame._layout.state.current_id
    if current_id == playlist_id:
        return
    frame._layout.set_current(playlist_id)
    frame._current_index = frame._layout.current_index()
    frame._update_active_playlist_styles()
    panel = frame._playlists.get(playlist_id)
    if panel:
        frame._announce_event("playlist", f"{ANNOUNCEMENT_PREFIX}{panel.model.name}")
        if isinstance(panel, PlaylistPanel) and panel.model.kind is PlaylistKind.MUSIC:
            frame._last_music_playlist_id = playlist_id


def update_active_playlist_styles(frame) -> None:
    active_colour = wx.Colour(230, 240, 255)
    inactive_colour = frame._playlist_container.GetBackgroundColour()
    active_text_colour = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
    inactive_text_colour = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)

    current_id = frame._layout.state.current_id
    for playlist_id, wrapper in frame._playlist_wrappers.items():
        is_active = playlist_id == current_id
        wrapper.SetBackgroundColour(active_colour if is_active else inactive_colour)
        wrapper.Refresh()
        panel = frame._playlists.get(playlist_id)
        if panel:
            panel.set_active(is_active)

    for playlist_id, header in frame._playlist_headers.items():
        is_active = playlist_id == current_id
        base_title = frame._playlist_titles.get(playlist_id, header.GetLabel())
        if header.GetLabel() != base_title:
            header.SetLabel(base_title)
        header.SetForegroundColour(active_text_colour if is_active else inactive_text_colour)
        header.Refresh()

    frame._playlist_container.Refresh()


def maybe_focus_playing_item(frame, panel: PlaylistPanel, item_id: str) -> None:
    if not frame._focus_playing_track:
        return
    playlist_id = panel.model.id
    if frame._focus_lock.get(playlist_id):
        current = panel.get_selected_indices()
        if len(current) == 1:
            selected_index = current[0]
            if 0 <= selected_index < len(panel.model.items):
                if panel.model.items[selected_index].id == item_id:
                    frame._focus_lock[playlist_id] = False
                else:
                    return
        else:
            return
    else:
        current = panel.get_selected_indices()
        if len(current) == 1:
            selected_index = current[0]
            if 0 <= selected_index < len(panel.model.items):
                if panel.model.items[selected_index].id == item_id:
                    return
    for index, track in enumerate(panel.model.items):
        if track.id == item_id:
            panel.select_index(index)
            frame._focus_lock[playlist_id] = False
            break
