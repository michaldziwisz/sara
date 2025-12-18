"""Playlist management actions extracted from the main frame."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import wx

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistKind, PlaylistModel
from sara.ui.dialogs.manage_playlists_dialog import ManagePlaylistsDialog
from sara.ui.file_selection_dialog import FileSelectionDialog
from sara.ui.new_playlist_dialog import NewPlaylistDialog
from sara.ui.playlist_devices_dialog import PlaylistDevicesDialog
from sara.ui.playlist_panel import PlaylistPanel


def prompt_new_playlist(frame) -> PlaylistModel | None:
    dialog = NewPlaylistDialog(frame)
    try:
        if dialog.ShowModal() != wx.ID_OK:
            return None
        model = frame._playlist_factory.create_playlist(
            dialog.playlist_name,
            kind=dialog.playlist_kind,
            folder_path=dialog.folder_path if dialog.playlist_kind is PlaylistKind.FOLDER else None,
        )
        frame.add_playlist(model)
        if dialog.playlist_kind is not PlaylistKind.FOLDER:
            frame._configure_playlist_devices(model.id)
        return model
    finally:
        dialog.Destroy()


def on_add_tracks(frame, _event: wx.CommandEvent) -> None:
    panel = frame._get_current_music_panel()
    if panel is None:
        frame._announce_event("playlist", _("Select a playlist first"))
        return

    style = wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE
    wildcard = _("Audio files (*.mp3;*.mp2;*.wav;*.flac;*.ogg)|*.mp3;*.mp2;*.wav;*.flac;*.ogg|All files|*.*")
    dialog = FileSelectionDialog(
        frame,
        title=_("Select audio files"),
        wildcard=wildcard,
        style=style,
    )
    result = dialog.ShowModal()
    paths = [Path(path) for path in dialog.get_paths()] if result == wx.ID_OK else []
    dialog.Destroy()
    if result != wx.ID_OK:
        return

    if not paths:
        frame._announce_event("playlist", _("No tracks were added"))
        return

    description = _("Loading %d selected tracks…") % len(paths)
    frame._run_item_loader(
        description=description,
        worker=lambda paths=paths: frame._create_items_from_paths(paths),
        on_complete=lambda items, panel=panel: frame._finalize_add_tracks(panel, items),
    )


def finalize_add_tracks(frame, panel: PlaylistPanel, new_items: list[PlaylistItem]) -> None:
    playlist_id = panel.model.id
    if playlist_id not in frame._playlists or frame._playlists.get(playlist_id) is not panel:
        return
    if not new_items:
        frame._announce_event("playlist", _("No tracks were added"))
        return
    panel.append_items(new_items)
    frame._announce_event(
        "playlist",
        _("Added %d tracks to playlist %s") % (len(new_items), panel.model.name),
    )


def on_remove_playlist(frame, _event: wx.CommandEvent) -> None:
    playlist_id = frame._layout.state.current_id
    if not playlist_id:
        frame._announce_event("playlist", _("No playlist selected"))
        return
    title = frame._playlist_titles.get(playlist_id, _("playlist"))
    response = wx.MessageBox(
        _("Remove playlist %s?") % title,
        _("Confirm removal"),
        style=wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        parent=frame,
    )
    if response != wx.YES:
        return
    if not frame._remove_playlist_by_id(playlist_id):
        frame._announce_event("playlist", _("Unable to remove playlist"))


def on_manage_playlists(frame, _event: wx.CommandEvent) -> None:
    entries: list[dict[str, Any]] = []
    for playlist_id in frame._layout.state.order:
        panel = frame._playlists.get(playlist_id)
        if not panel:
            continue
        name = frame._playlist_titles.get(playlist_id, panel.model.name)
        entries.append(
            {
                "id": playlist_id,
                "name": name,
                "kind": panel.model.kind,
                "slots": list(panel.model.get_configured_slots()),
            }
        )
    if not entries:
        frame._announce_event("playlist", _("No playlists available"))
        return
    dialog = ManagePlaylistsDialog(
        frame,
        entries,
        create_callback=frame._prompt_new_playlist,
        configure_callback=frame._configure_playlist_devices,
    )
    try:
        if dialog.ShowModal() != wx.ID_OK:
            return
        result = dialog.get_result()
    finally:
        dialog.Destroy()
    if not result:
        return
    removed = result["removed"]
    for playlist_id in removed:
        frame._remove_playlist_by_id(playlist_id, announce=False)
    frame._apply_playlist_order(result["order"])
    if removed:
        frame._announce_event("playlist", _("Removed %d playlists") % len(removed))


def on_assign_device(frame, _event: wx.CommandEvent) -> None:
    panel = frame._get_current_playlist_panel()
    if panel is None:
        frame._announce_event("playlist", _("Select a playlist first"))
        return
    if isinstance(panel, PlaylistPanel) and panel.model.kind is PlaylistKind.FOLDER:
        frame._announce_event("playlist", _("Music folders use the configured PFL device"))
        return
    frame._configure_playlist_devices(panel.model.id)


def configure_playlist_devices(frame, playlist_id: str) -> list[str | None] | None:
    panel = frame._playlists.get(playlist_id)
    if panel is None:
        return None
    devices = frame._audio_engine.get_devices()
    if not devices:
        frame._announce_event("device", _("No audio devices available"))
        return None
    model = panel.model
    dialog = PlaylistDevicesDialog(frame, devices=devices, slots=model.get_configured_slots())
    try:
        if dialog.ShowModal() != wx.ID_OK:
            return None
        slots = dialog.get_slots()
    finally:
        dialog.Destroy()

    model.set_output_slots(slots)
    frame._persist_playlist_outputs(model)

    device_map = {device.id: device for device in devices}
    assigned_names = [device_map[device_id].name for device_id in slots if device_id and device_id in device_map]
    if assigned_names:
        frame._announce_event(
            "playlist",
            _("Playlist %s assigned to players: %s") % (model.name, ", ".join(assigned_names)),
        )
    else:
        frame._announce_event(
            "playlist",
            _("Removed device assignments for playlist %s") % model.name,
        )
    return slots

