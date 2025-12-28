"""Folder playlist actions."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import wx

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistKind, PlaylistModel
from sara.ui.file_selection_dialog import FileSelectionDialog
from sara.ui.folder_playlist_panel import FolderPlaylistPanel
from sara.ui.playlist_panel import PlaylistPanel
from sara.ui.undo import InsertOperation


def select_folder_for_playlist(frame, playlist_id: str) -> None:
    panel = frame._playlists.get(playlist_id)
    if not isinstance(panel, FolderPlaylistPanel):
        return
    dialog = FileSelectionDialog(
        frame,
        title=_("Select folder"),
        allow_directories=True,
        directories_only=True,
    )
    try:
        if dialog.ShowModal() != wx.ID_OK:
            return
        paths = dialog.get_paths()
    finally:
        dialog.Destroy()
    if not paths:
        return
    selected = Path(paths[0])
    if not selected.exists() or not selected.is_dir():
        frame._announce_event("playlist", _("Folder %s does not exist") % selected)
        return
    panel.model.folder_path = selected
    panel.set_folder_path(selected)
    load_folder_playlist(frame, panel.model)


def reload_folder_playlist(frame, playlist_id: str) -> None:
    panel = frame._playlists.get(playlist_id)
    if not isinstance(panel, FolderPlaylistPanel):
        return
    folder_path = panel.model.folder_path
    if not folder_path:
        frame._announce_event("playlist", _("Select a folder first"))
        return
    load_folder_playlist(frame, panel.model)


def load_folder_playlist(frame, playlist: PlaylistModel, *, announce: bool = True) -> None:
    folder_path = playlist.folder_path
    if not folder_path:
        frame._announce_event("playlist", _("Select a folder first"))
        return
    if not folder_path.exists():
        frame._announce_event("playlist", _("Folder %s does not exist") % folder_path)
        return
    description = _("Loading folder %s…") % folder_path.name
    frame._run_item_loader(
        description=description,
        worker=lambda folder=folder_path: load_folder_items(frame, folder),
        on_complete=lambda result, playlist_id=playlist.id, folder=folder_path: finalize_folder_load(
            frame,
            playlist_id,
            folder,
            result,
            announce=announce,
        ),
    )


def load_folder_items(frame, folder_path: Path) -> tuple[list[PlaylistItem], int]:
    file_paths, skipped = frame._collect_files_from_paths([folder_path])
    items = frame._create_items_from_paths(file_paths)
    return items, skipped


def finalize_folder_load(
    frame,
    playlist_id: str,
    folder_path: Path,
    result: tuple[list[PlaylistItem], int] | list[PlaylistItem],
    *,
    announce: bool,
) -> None:
    panel = frame._playlists.get(playlist_id)
    if not isinstance(panel, FolderPlaylistPanel):
        return
    if playlist_id not in frame._playlists or panel.model is None:
        return
    if isinstance(result, tuple):
        items, skipped = result
    else:
        items, skipped = result, 0
    panel.model.items = items
    panel.model.folder_path = folder_path
    panel.set_folder_path(folder_path)
    panel.refresh(selected_indices=None, focus=False)
    if announce:
        frame._announce_event(
            "playlist",
            _("Loaded %d tracks from %s") % (len(items), folder_path.name),
        )
    if skipped:
        noun = _("file") if skipped == 1 else _("files")
        frame._announce_event("playlist", _("Skipped %d unsupported %s") % (skipped, noun))


def handle_folder_preview(frame, playlist_id: str, item_id: str) -> None:
    panel = frame._playlists.get(playlist_id)
    if not isinstance(panel, FolderPlaylistPanel):
        return
    item = panel.model.get_item(item_id)
    if not item:
        return
    if frame._active_folder_preview == (playlist_id, item_id):
        if frame._playback.preview_context:
            stop_preview(frame)
            return
        frame._active_folder_preview = None
    if frame._playback.start_preview(item, 0.0):
        frame._active_folder_preview = (playlist_id, item_id)


def stop_preview(frame) -> None:
    try:
        frame._playback.stop_preview()
    finally:
        frame._active_folder_preview = None


def send_folder_items_to_music(frame, playlist_id: str, item_ids: Sequence[str]) -> None:
    panel = frame._playlists.get(playlist_id)
    if not isinstance(panel, FolderPlaylistPanel):
        return
    target = target_music_playlist(frame)
    if not target:
        frame._announce_event("playlist", _("Add a music playlist first"))
        return
    target_panel, target_model = target
    source_items = [panel.model.get_item(item_id) for item_id in item_ids]
    source_items = [item for item in source_items if item]
    if not source_items:
        frame._announce_event("playlist", _("No tracks selected"))
        return
    serialized = frame._serialize_items(source_items)
    new_items = [frame._create_item_from_serialized(data) for data in serialized]
    selected_indices = target_panel.get_selected_indices()
    anchor = selected_indices[-1] if selected_indices else None
    insert_at = anchor + 1 if anchor is not None else len(target_model.items)
    target_model.items[insert_at:insert_at] = new_items
    insert_indices = list(range(insert_at, insert_at + len(new_items)))
    target_panel.refresh(insert_indices, focus=False)
    frame._announce_event(
        "playlist",
        _("Added %d tracks to playlist %s") % (len(new_items), target_model.name),
    )
    operation = InsertOperation(indices=list(insert_indices), items=list(new_items))
    frame._push_undo_action(target_model, operation)


def target_music_playlist(frame) -> tuple[PlaylistPanel, PlaylistModel] | None:
    candidate_ids: list[str] = []
    if frame._last_music_playlist_id:
        candidate_ids.append(frame._last_music_playlist_id)
    for playlist_id in frame._layout.state.order:
        if playlist_id not in candidate_ids:
            candidate_ids.append(playlist_id)
    for playlist_id in candidate_ids:
        panel = frame._playlists.get(playlist_id)
        if isinstance(panel, PlaylistPanel) and panel.model.kind is PlaylistKind.MUSIC:
            frame._last_music_playlist_id = playlist_id
            return panel, panel.model
    return None
