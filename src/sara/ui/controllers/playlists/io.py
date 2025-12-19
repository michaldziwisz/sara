"""Playlist import/export actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import wx

from sara.core.i18n import gettext as _
from sara.core.m3u import parse_m3u_lines, serialize_m3u
from sara.core.playlist import PlaylistKind
from sara.ui.file_selection_dialog import FileSelectionDialog
from sara.ui.news_playlist_panel import NewsPlaylistPanel
from sara.ui.playlist_panel import PlaylistPanel


def parse_m3u(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception as exc:  # pylint: disable=broad-except
        raise RuntimeError(_("Failed to read playlist file: %s") % exc) from exc
    return parse_m3u_lines(lines)


def on_import_playlist(frame, _event: wx.CommandEvent) -> None:
    panel = frame._get_current_playlist_panel()
    if panel is None:
        frame._announce_event("playlist", _("Select a playlist first"))
        return
    if isinstance(panel, NewsPlaylistPanel):
        result = panel.prompt_load_service()
        if result:
            frame._announce_event(
                "import_export",
                _("Imported news service from %s") % result.name,
            )
        return
    if not isinstance(panel, PlaylistPanel):
        frame._announce_event("playlist", _("Active playlist does not support import"))
        return
    if panel.model.kind is PlaylistKind.FOLDER:
        frame._announce_event("playlist", _("Music folder playlists do not support import"))
        return

    dialog = FileSelectionDialog(
        frame,
        title=_("Import playlist"),
        message=_("Select playlist"),
        wildcard=_("M3U playlists (*.m3u)|*.m3u|All files|*.*"),
        style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
    )
    result = dialog.ShowModal()
    selected_paths = dialog.get_paths() if result == wx.ID_OK else []
    dialog.Destroy()
    if result != wx.ID_OK or not selected_paths:
        return

    path = Path(selected_paths[0])

    try:
        entries = parse_m3u(path)
    except Exception as exc:  # pylint: disable=broad-except
        frame._announce_event("import_export", _("Failed to import playlist: %s") % exc)
        return

    if not entries:
        frame._announce_event("import_export", _("Playlist file is empty"))
        return

    description = _("Importing tracks from %s…") % path.name
    frame._run_item_loader(
        description=description,
        worker=lambda entries=entries: frame._create_items_from_m3u_entries(entries),
        on_complete=lambda items, panel=panel, filename=path.name: frame._finalize_import_playlist(
            panel, items, filename
        ),
    )


def on_export_playlist(frame, _event: wx.CommandEvent) -> None:
    panel = frame._get_current_playlist_panel()
    if panel is None:
        frame._announce_event("playlist", _("Select a playlist first"))
        return
    if isinstance(panel, NewsPlaylistPanel):
        result = panel.prompt_save_service()
        if result:
            frame._announce_event(
                "import_export",
                _("Saved news service to %s") % result.name,
            )
        return
    if not isinstance(panel, PlaylistPanel):
        frame._announce_event("playlist", _("Active playlist does not support export"))
        return
    if panel.model.kind is PlaylistKind.FOLDER:
        frame._announce_event("playlist", _("Music folder playlists do not support export"))
        return

    dialog = FileSelectionDialog(
        frame,
        title=_("Save playlist"),
        message=_("Save playlist"),
        wildcard=_("M3U playlists (*.m3u)|*.m3u|All files|*.*"),
        style=wx.FD_SAVE,
    )
    result = dialog.ShowModal()
    selected_paths = dialog.get_paths() if result == wx.ID_OK else []
    dialog.Destroy()
    if result != wx.ID_OK or not selected_paths:
        return

    path = Path(selected_paths[0])

    try:
        path.write_text(serialize_m3u(panel.model.items), encoding="utf-8")
    except Exception as exc:  # pylint: disable=broad-except
        frame._announce_event("import_export", _("Failed to save playlist: %s") % exc)
        return

    frame._announce_event("import_export", _("Playlist saved to %s") % path.name)
