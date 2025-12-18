"""Menu/accelerator wiring extracted from the main frame."""

from __future__ import annotations

import wx

from sara.core.i18n import gettext as _
from sara.core.shortcuts import get_shortcut
from sara.ui.shortcut_utils import format_shortcut_display, parse_shortcut


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


def should_handle_altgr_track_remaining(event: wx.KeyEvent, keycode: int) -> bool:
    if keycode not in (ord("T"), ord("t")):
        return False
    modifiers = event.GetModifiers()
    altgr_flag = getattr(wx, "MOD_ALTGR", None)
    if isinstance(modifiers, int) and altgr_flag and modifiers & altgr_flag:
        return True
    if event.AltDown() and event.ControlDown() and not event.MetaDown():
        return True
    return False


def handle_global_char_hook(frame, event: wx.KeyEvent) -> None:
    keycode = event.GetKeyCode()
    if should_handle_altgr_track_remaining(event, keycode):
        frame._on_track_remaining()
        return
    if keycode == wx.WXK_F6:
        if frame._cycle_playlist_focus(backwards=event.ShiftDown()):
            return
    if handle_jingles_key(frame, event):
        return
    panel, focus = frame._active_news_panel()
    if keycode == wx.WXK_SPACE and panel and panel.is_edit_control(focus):
        event.Skip()
        event.StopPropagation()
        return
    event.Skip()


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
    frame.Bind(wx.EVT_MENU, frame._on_move_selection_up, id=int(frame._move_up_id))
    frame.Bind(wx.EVT_MENU, frame._on_move_selection_down, id=int(frame._move_down_id))
    frame.Bind(wx.EVT_CHAR_HOOK, frame._handle_global_char_hook)


def configure_accelerators(frame) -> None:
    accel_entries: list[tuple[int, int, int]] = []
    frame._playlist_hotkey_defaults = frame._settings.get_playlist_shortcuts()
    frame._playlist_action_ids.clear()
    frame._action_by_id.clear()

    def add_entry(scope: str, action: str, command_id: int) -> None:
        shortcut_value = frame._settings.get_shortcut(scope, action)
        modifiers_key = parse_shortcut(shortcut_value)
        if not modifiers_key:
            descriptor = get_shortcut(scope, action)
            if descriptor:
                modifiers_key = parse_shortcut(descriptor.default)
        if not modifiers_key:
            return
        modifiers, keycode = modifiers_key
        accel_entries.append((modifiers, keycode, command_id))
        if keycode == wx.WXK_RETURN:
            accel_entries.append((modifiers, wx.WXK_NUMPAD_ENTER, command_id))

    play_next_id = int(frame._play_next_id)
    add_entry("global", "play_next", play_next_id)
    frame.Bind(wx.EVT_MENU, frame._on_global_play_next, id=play_next_id)

    auto_mix_id = int(frame._auto_mix_toggle_id)
    add_entry("global", "auto_mix_toggle", auto_mix_id)
    frame.Bind(wx.EVT_MENU, frame._on_toggle_auto_mix, id=auto_mix_id)

    add_entry("global", "loop_playback_toggle", int(frame._loop_playback_toggle_id))
    add_entry("global", "loop_info", int(frame._loop_info_id))
    add_entry("global", "track_remaining", int(frame._track_remaining_id))

    add_entry("playlist_menu", "new", wx.ID_NEW)
    add_entry("playlist_menu", "add_tracks", int(frame._add_tracks_id))
    add_entry("playlist_menu", "assign_device", int(frame._assign_device_id))
    add_entry("playlist_menu", "import", wx.ID_OPEN)
    add_entry("playlist_menu", "remove", int(frame._remove_playlist_id))
    add_entry("playlist_menu", "manage", int(frame._manage_playlists_id))
    add_entry("playlist_menu", "exit", wx.ID_EXIT)

    add_entry("edit", "undo", int(frame._undo_id))
    add_entry("edit", "redo", int(frame._redo_id))
    add_entry("edit", "cut", int(frame._cut_id))
    add_entry("edit", "copy", int(frame._copy_id))
    add_entry("edit", "paste", int(frame._paste_id))
    add_entry("edit", "delete", int(frame._delete_id))
    add_entry("edit", "move_up", int(frame._move_up_id))
    add_entry("edit", "move_down", int(frame._move_down_id))

    for action, key in frame._playlist_hotkey_defaults.items():
        parsed_action = parse_shortcut(key)
        if not parsed_action:
            descriptor = get_shortcut("playlist", action)
            if descriptor:
                parsed_action = parse_shortcut(descriptor.default)
        if not parsed_action:
            continue
        modifiers, keycode = parsed_action
        cmd_id_ref = wx.NewIdRef()
        cmd_id = int(cmd_id_ref)
        frame._playlist_action_ids[action] = cmd_id
        frame._action_by_id[cmd_id] = action
        accel_entries.append((modifiers, keycode, cmd_id))
        if keycode == wx.WXK_RETURN:
            accel_entries.append((modifiers, wx.WXK_NUMPAD_ENTER, cmd_id))
        frame.Bind(wx.EVT_MENU, frame._on_playlist_hotkey, id=cmd_id)

    accel_table = wx.AcceleratorTable(accel_entries)
    frame.SetAcceleratorTable(accel_table)


def handle_jingles_key(frame, event: wx.KeyEvent) -> bool:
    panel = frame._get_current_music_panel()
    if panel is None:
        return False
    focus = wx.Window.FindFocus()
    if not panel.is_list_control(focus):
        return False
    if event.ControlDown() or event.AltDown() or event.MetaDown():
        return False

    keycode = event.GetKeyCode()

    slot_index: int | None = None
    if ord("0") <= keycode <= ord("9"):
        digit = chr(keycode)
        slot_index = 9 if digit == "0" else int(digit) - 1
    else:
        numpad_map = {
            wx.WXK_NUMPAD1: 0,
            wx.WXK_NUMPAD2: 1,
            wx.WXK_NUMPAD3: 2,
            wx.WXK_NUMPAD4: 3,
            wx.WXK_NUMPAD5: 4,
            wx.WXK_NUMPAD6: 5,
            wx.WXK_NUMPAD7: 6,
            wx.WXK_NUMPAD8: 7,
            wx.WXK_NUMPAD9: 8,
            wx.WXK_NUMPAD0: 9,
        }
        slot_index = numpad_map.get(keycode)

    if slot_index is not None:
        overlay = bool(event.ShiftDown())
        if not frame._jingles.play_slot(slot_index, overlay=overlay):
            number_label = "0" if slot_index == 9 else str(slot_index + 1)
            frame._announce_event("jingles", _("Empty jingle slot %s") % number_label)
        event.StopPropagation()
        event.Skip(False)
        return True

    prev_keys = {ord("-"), ord("_"), getattr(wx, "WXK_SUBTRACT", -1)}
    next_keys = {ord("="), ord("+"), getattr(wx, "WXK_ADD", -1)}
    if keycode in prev_keys:
        frame._jingles.prev_page()
        event.StopPropagation()
        event.Skip(False)
        return True
    if keycode in next_keys:
        frame._jingles.next_page()
        event.StopPropagation()
        event.Skip(False)
        return True

    return False
