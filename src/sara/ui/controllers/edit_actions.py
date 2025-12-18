"""Edit/clipboard/undo actions extracted from the main frame."""

from __future__ import annotations

import logging

import wx

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistKind, PlaylistModel
from sara.ui.playlist_panel import PlaylistPanel
from sara.ui.undo import InsertOperation, MoveOperation, RemoveOperation, UndoAction


logger = logging.getLogger(__name__)


def push_undo_action(frame, model: PlaylistModel, operation) -> None:
    frame._undo_manager.push(UndoAction(model.id, operation))


def apply_undo_callback(frame, action: UndoAction, reverse: bool) -> bool:
    model = frame._get_playlist_model(action.playlist_id)
    panel = frame._playlists.get(action.playlist_id)
    if model is None or panel is None:
        return False
    if frame._layout.state.current_id != action.playlist_id:
        frame._layout.set_current(action.playlist_id)
        frame._update_active_playlist_styles()
    try:
        indices = action.revert(model) if reverse else action.apply(model)
    except ValueError as exc:
        logger.error("Undo operation failed: %s", exc)
        return False
    selection = indices if indices else []
    frame._refresh_playlist_view(panel, selection)
    return True


def on_copy_selection(frame, _event: wx.CommandEvent) -> None:
    context = frame._get_selected_items(kinds=(PlaylistKind.MUSIC, PlaylistKind.FOLDER))
    if context is None:
        return
    panel, model, selected = context
    items = [item for _, item in selected]
    frame._clipboard.set(frame._serialize_items(items))
    existing_paths = [item.path for item in items if item.path.exists()]
    if existing_paths:
        frame._set_system_clipboard_paths(existing_paths)
    count = len(items)
    noun = _("track") if count == 1 else _("tracks")
    frame._announce_event(
        "clipboard",
        _("Copied %d %s from playlist %s") % (count, noun, model.name),
    )
    panel.focus_list()


def on_cut_selection(frame, _event: wx.CommandEvent) -> None:
    context = frame._get_selected_items()
    if context is None:
        return
    panel, model, selected = context
    items = [item for _, item in selected]
    frame._clipboard.set(frame._serialize_items(items))
    existing_paths = [item.path for item in items if item.path.exists()]
    if existing_paths:
        frame._set_system_clipboard_paths(existing_paths)
    indices = sorted(index for index, _ in selected)
    removed_items = frame._remove_items(panel, model, indices)
    count = len(items)
    noun = _("track") if count == 1 else _("tracks")
    frame._announce_event("clipboard", _("Cut %d %s") % (count, noun))
    if removed_items:
        operation = RemoveOperation(indices=list(indices), items=list(removed_items))
        frame._push_undo_action(model, operation)


def on_paste_selection(frame, _event: wx.CommandEvent) -> None:
    context = frame._get_selected_context()
    panel: PlaylistPanel
    if context is None:
        panel = frame._get_current_music_panel()
        if panel is None:
            return
        model = panel.model
        indices: list[int] = []
    else:
        panel, model, indices = context
    index = indices[-1] if indices else None
    insert_at = index + 1 if index is not None else len(model.items)

    clipboard_paths = frame._get_system_clipboard_paths()
    if clipboard_paths:
        file_paths, skipped = frame._collect_files_from_paths(clipboard_paths)
        if not file_paths:
            if skipped:
                frame._announce_event("clipboard", _("Clipboard does not contain supported audio files"))
            else:
                frame._announce_event("clipboard", _("Clipboard does not contain files or folders"))
            return

        description = _("Loading tracks from clipboard…")
        frame._run_item_loader(
            description=description,
            worker=lambda file_paths=file_paths: frame._create_items_from_paths(file_paths),
            on_complete=lambda items, panel=panel, model=model, insert_at=insert_at, anchor=index, skipped=skipped: frame._finalize_clipboard_paste(
                panel,
                model,
                items,
                insert_at,
                anchor,
                skipped_files=skipped,
            ),
        )
        return

    if not frame._clipboard.is_empty():
        new_items = [frame._create_item_from_serialized(data) for data in frame._clipboard.get()]
        frame._finalize_clipboard_paste(panel, model, new_items, insert_at, index, skipped_files=0)
        return

    frame._announce_event("clipboard", _("Clipboard is empty"))
    return


def finalize_clipboard_paste(
    frame,
    panel: PlaylistPanel,
    model: PlaylistModel,
    items: list[PlaylistItem],
    insert_at: int,
    anchor_index: int | None,
    *,
    skipped_files: int,
) -> None:
    playlist_id = panel.model.id
    if playlist_id not in frame._playlists or frame._playlists.get(playlist_id) is not panel:
        return
    if not items:
        selection = [anchor_index] if anchor_index is not None and anchor_index < len(model.items) else None
        frame._refresh_playlist_view(panel, selection)
        frame._announce_event("clipboard", _("No supported audio files found on the clipboard"))
        return

    insert_at = max(0, min(insert_at, len(model.items)))
    model.items[insert_at:insert_at] = items
    insert_indices = list(range(insert_at, insert_at + len(items)))
    frame._refresh_playlist_view(panel, insert_indices)
    count = len(items)
    noun = _("track") if count == 1 else _("tracks")
    frame._announce_event("clipboard", _("Pasted %d %s") % (count, noun))
    operation = InsertOperation(indices=list(insert_indices), items=list(items))
    frame._push_undo_action(model, operation)
    if skipped_files:
        noun = _("file") if skipped_files == 1 else _("files")
        frame._announce_event("clipboard", _("Skipped %d unsupported %s") % (skipped_files, noun))

    return


def on_delete_selection(frame, _event: wx.CommandEvent) -> None:
    context = frame._get_selected_items()
    if context is None:
        return
    panel, model, selected = context
    items = [item for _, item in selected]
    indices = sorted(index for index, _ in selected)
    removed_items = frame._remove_items(panel, model, indices)
    count = len(items)
    noun = _("track") if count == 1 else _("tracks")
    frame._announce_event("clipboard", _("Deleted %d %s") % (count, noun))
    if removed_items:
        operation = RemoveOperation(indices=list(indices), items=list(removed_items))
        frame._push_undo_action(model, operation)


def move_selection(frame, delta: int) -> None:
    context = frame._get_selected_items()
    if context is None:
        return
    panel, model, selected = context
    indices = [index for index, _item in selected]
    operation = MoveOperation(original_indices=list(indices), delta=delta)
    try:
        new_indices = operation.apply(model)
    except ValueError:
        direction = _("up") if delta < 0 else _("down")
        frame._announce_event("clipboard", _("Cannot move further %s") % direction)
        return

    frame._refresh_playlist_view(panel, new_indices)
    frame._push_undo_action(model, operation)
    count = len(selected)
    if count == 1:
        frame._announce_event("clipboard", _("Moved %s") % selected[0][1].title)
    else:
        noun = _("track") if count == 1 else _("tracks")
        frame._announce_event("clipboard", _("Moved %d %s") % (count, noun))


def on_undo(frame, _event: wx.CommandEvent) -> None:
    if not frame._undo_manager.undo():
        frame._announce_event("undo_redo", _("Nothing to undo"))
        return
    frame._announce_event("undo_redo", _("Undo operation"))


def on_redo(frame, _event: wx.CommandEvent) -> None:
    if not frame._undo_manager.redo():
        frame._announce_event("undo_redo", _("Nothing to redo"))
        return
    frame._announce_event("undo_redo", _("Redo operation"))

