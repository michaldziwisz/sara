"""Accelerator table setup extracted from the main frame."""

from __future__ import annotations

import wx

from sara.core.shortcuts import get_shortcut
from sara.ui.shortcut_utils import parse_shortcut


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

