"""Menu bar construction extracted from the main frame."""

from __future__ import annotations

import wx

from sara.core.i18n import gettext as _
from sara.core.shortcuts import get_shortcut
from sara.ui.shortcut_utils import format_shortcut_display


def append_shortcut_menu_item(
    frame,
    menu: wx.Menu,
    command_id: wx.WindowIDRef | int,
    base_label: str,
    scope: str,
    action: str,
    *,
    check: bool = False,
) -> wx.MenuItem:
    item_id = int(command_id)
    menu_item = menu.AppendCheckItem(item_id, base_label) if check else menu.Append(item_id, base_label)
    register_menu_shortcut(frame, menu_item, base_label, scope, action)
    return menu_item


def register_menu_shortcut(frame, menu_item: wx.MenuItem, base_label: str, scope: str, action: str) -> None:
    if get_shortcut(scope, action) is None:
        raise ValueError(f"Shortcut not registered for action {scope}:{action}")
    frame._shortcut_menu_items[(scope, action)] = (menu_item, base_label)
    apply_shortcut_to_menu_item(frame, scope, action)


def apply_shortcut_to_menu_item(frame, scope: str, action: str) -> None:
    entry = frame._shortcut_menu_items.get((scope, action))
    if not entry:
        return
    menu_item, base_label = entry
    shortcut_value = frame._settings.get_shortcut(scope, action)
    shortcut_label = format_shortcut_display(shortcut_value)
    label = base_label if not shortcut_label else f"{base_label}\t{shortcut_label}"
    menu_item.SetItemLabel(label)


def update_shortcut_menu_labels(frame) -> None:
    for scope, action in frame._shortcut_menu_items.keys():
        apply_shortcut_to_menu_item(frame, scope, action)


def create_menu_bar(frame) -> None:
    menu_bar = wx.MenuBar()

    frame._shortcut_menu_items.clear()

    playlist_menu = wx.Menu()
    new_item = playlist_menu.Append(wx.ID_NEW, _("&New playlist"))
    register_menu_shortcut(frame, new_item, _("&New playlist"), "playlist_menu", "new")
    add_tracks_item = playlist_menu.Append(int(frame._add_tracks_id), _("Add &tracks…"))
    register_menu_shortcut(frame, add_tracks_item, _("Add &tracks…"), "playlist_menu", "add_tracks")
    assign_device_item = playlist_menu.Append(int(frame._assign_device_id), _("Assign &audio device…"))
    register_menu_shortcut(
        frame, assign_device_item, _("Assign &audio device…"), "playlist_menu", "assign_device"
    )
    import_item = playlist_menu.Append(wx.ID_OPEN, _("&Import playlist"))
    register_menu_shortcut(frame, import_item, _("&Import playlist"), "playlist_menu", "import")
    playlist_menu.AppendSeparator()
    remove_item = playlist_menu.Append(int(frame._remove_playlist_id), _("&Remove playlist"))
    manage_item = playlist_menu.Append(int(frame._manage_playlists_id), _("Manage &playlists…"))
    register_menu_shortcut(frame, remove_item, _("&Remove playlist"), "playlist_menu", "remove")
    register_menu_shortcut(frame, manage_item, _("Manage &playlists…"), "playlist_menu", "manage")
    playlist_menu.AppendSeparator()
    export_item = playlist_menu.Append(wx.ID_SAVE, _("&Export playlist…"))
    register_menu_shortcut(frame, export_item, _("&Export playlist…"), "playlist_menu", "export")
    exit_item = playlist_menu.Append(wx.ID_EXIT, _("E&xit"))
    register_menu_shortcut(frame, exit_item, _("E&xit"), "playlist_menu", "exit")
    menu_bar.Append(playlist_menu, _("&Playlist"))

    edit_menu = wx.Menu()
    append_shortcut_menu_item(frame, edit_menu, frame._undo_id, _("&Undo"), "edit", "undo")
    append_shortcut_menu_item(frame, edit_menu, frame._redo_id, _("Re&do"), "edit", "redo")
    edit_menu.AppendSeparator()
    append_shortcut_menu_item(frame, edit_menu, frame._cut_id, _("Cu&t"), "edit", "cut")
    append_shortcut_menu_item(frame, edit_menu, frame._copy_id, _("&Copy"), "edit", "copy")
    append_shortcut_menu_item(frame, edit_menu, frame._paste_id, _("&Paste"), "edit", "paste")
    edit_menu.AppendSeparator()
    append_shortcut_menu_item(frame, edit_menu, frame._delete_id, _("&Delete"), "edit", "delete")
    edit_menu.AppendSeparator()
    append_shortcut_menu_item(frame, edit_menu, frame._mark_as_song_id, _("Mark as &song"), "edit", "mark_as_song")
    append_shortcut_menu_item(frame, edit_menu, frame._mark_as_spot_id, _("Mark as s&pot"), "edit", "mark_as_spot")
    edit_menu.AppendSeparator()
    append_shortcut_menu_item(frame, edit_menu, frame._move_up_id, _("Move &up"), "edit", "move_up")
    append_shortcut_menu_item(frame, edit_menu, frame._move_down_id, _("Move &down"), "edit", "move_down")
    menu_bar.Append(edit_menu, _("&Edit"))

    tools_menu = wx.Menu()
    options_id = wx.NewIdRef()
    append_shortcut_menu_item(
        frame,
        tools_menu,
        frame._loop_playback_toggle_id,
        _("Toggle track &loop"),
        "global",
        "loop_playback_toggle",
    )

    append_shortcut_menu_item(
        frame,
        tools_menu,
        frame._loop_info_id,
        _("Loop &information"),
        "global",
        "loop_info",
    )
    append_shortcut_menu_item(
        frame,
        tools_menu,
        frame._track_remaining_id,
        _("Track &remaining time"),
        "global",
        "track_remaining",
    )

    tools_menu.Append(int(frame._shortcut_editor_id), _("Edit &shortcuts…"))
    tools_menu.Append(int(frame._jingles_manage_id), _("&Jingles…"))
    tools_menu.Append(int(options_id), _("&Options…"))
    menu_bar.Append(tools_menu, _("&Tools"))

    help_menu = wx.Menu()
    help_menu.Append(int(frame._send_feedback_id), _("Send &feedback…"))
    menu_bar.Append(help_menu, _("&Help"))

    frame.SetMenuBar(menu_bar)

    frame.Bind(wx.EVT_MENU, frame._on_new_playlist, id=wx.ID_NEW)
    frame.Bind(wx.EVT_MENU, frame._on_add_tracks, id=frame._add_tracks_id)
    frame.Bind(wx.EVT_MENU, frame._on_assign_device, id=frame._assign_device_id)
    frame.Bind(wx.EVT_MENU, frame._on_import_playlist, id=wx.ID_OPEN)
    frame.Bind(wx.EVT_MENU, frame._on_export_playlist, id=wx.ID_SAVE)
    frame.Bind(wx.EVT_MENU, frame._on_exit, id=wx.ID_EXIT)
    frame.Bind(wx.EVT_MENU, frame._on_remove_playlist, id=frame._remove_playlist_id)
    frame.Bind(wx.EVT_MENU, frame._on_manage_playlists, id=frame._manage_playlists_id)
    frame.Bind(wx.EVT_MENU, frame._on_options, id=int(options_id))
    frame.Bind(wx.EVT_MENU, frame._on_send_feedback, id=int(frame._send_feedback_id))
    frame.Bind(wx.EVT_MENU, frame._on_toggle_loop_playback, id=int(frame._loop_playback_toggle_id))
    frame.Bind(wx.EVT_MENU, frame._on_loop_info, id=int(frame._loop_info_id))
    frame.Bind(wx.EVT_MENU, frame._on_track_remaining, id=int(frame._track_remaining_id))
    frame.Bind(wx.EVT_MENU, frame._on_edit_shortcuts, id=int(frame._shortcut_editor_id))
    frame.Bind(wx.EVT_MENU, frame._on_jingles, id=int(frame._jingles_manage_id))
    frame.Bind(wx.EVT_MENU, frame._on_undo, id=int(frame._undo_id))
    frame.Bind(wx.EVT_MENU, frame._on_redo, id=int(frame._redo_id))
    frame.Bind(wx.EVT_MENU, frame._on_cut_selection, id=int(frame._cut_id))
    frame.Bind(wx.EVT_MENU, frame._on_copy_selection, id=int(frame._copy_id))
    frame.Bind(wx.EVT_MENU, frame._on_paste_selection, id=int(frame._paste_id))
    frame.Bind(wx.EVT_MENU, frame._on_delete_selection, id=int(frame._delete_id))
    frame.Bind(wx.EVT_MENU, frame._on_mark_as_song, id=int(frame._mark_as_song_id))
    frame.Bind(wx.EVT_MENU, frame._on_mark_as_spot, id=int(frame._mark_as_spot_id))
    frame.Bind(wx.EVT_MENU, frame._on_move_selection_up, id=int(frame._move_up_id))
    frame.Bind(wx.EVT_MENU, frame._on_move_selection_down, id=int(frame._move_down_id))
    frame.Bind(wx.EVT_CHAR_HOOK, frame._handle_global_char_hook)
