"""Wybór celu stołu, niezależny od aktywnego panelu i fokusu okna."""

from __future__ import annotations

from contextlib import contextmanager

from sara.core.playlist import PlaylistKind


def main_panel(frame):
    settings = getattr(frame, "_settings", None)
    playlist_id = settings.get_remote_main_playlist() if settings else ""
    panel = frame._playlists.get(playlist_id)
    if panel is not None and panel.model.kind is PlaylistKind.MUSIC:
        return panel
    for playlist_id in frame._layout.state.order:
        panel = frame._playlists.get(playlist_id)
        if panel is not None and panel.model.kind is PlaylistKind.MUSIC:
            return panel
    return None


@contextmanager
def background_selection(frame):
    """Zmiana wiersza ze stołu nie jest wejściem użytkownika do playlisty.

    ListCtrl.Select emituje synchroniczne EVT_LIST_ITEM_SELECTED, a istniejący
    handler aktywuje panel. Blokujemy tylko to zdarzenie na czas polecenia,
    również przy odświeżeniu po pauzie/stopie. Nie przenosimy fokusu tam i z powrotem.
    """
    blockers = []
    try:
        for panel in frame._playlists.values():
            control = getattr(panel, "_list_ctrl", None)
            if control is not None:
                import wx
                blockers.append(wx.EventBlocker(control, wx.EVT_LIST_ITEM_SELECTED.typeId))
        yield
    finally:
        blockers.clear()
