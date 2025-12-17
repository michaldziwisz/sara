"""Dialog for managing active playlists (order, removal, device slots)."""

from __future__ import annotations

from typing import Any, Callable, Optional

import wx

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistKind, PlaylistModel


class ManagePlaylistsDialog(wx.Dialog):
    """Allow users to reorder, remove, and configure active playlists."""

    KIND_LABELS = {
        PlaylistKind.MUSIC: _("Music"),
        PlaylistKind.NEWS: _("News"),
        PlaylistKind.FOLDER: _("Music folder"),
    }

    def __init__(
        self,
        parent: wx.Window,
        entries: list[dict[str, Any]],
        *,
        create_callback: Callable[[], PlaylistModel | None] | None = None,
        configure_callback: Callable[[str], list[str | None] | None] | None = None,
    ) -> None:
        super().__init__(parent, title=_("Manage playlists"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._entries: list[dict[str, Any]] = [
            {
                "id": entry["id"],
                "name": entry["name"],
                "kind": entry["kind"],
                "slots": list(entry.get("slots", [])),
            }
            for entry in entries
        ]
        self._removed: list[str] = []
        self._create_callback = create_callback
        self._configure_callback = configure_callback

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(self, label=_("Current playlists (top = first in sequence):"))
        main_sizer.Add(label, 0, wx.ALL, 5)

        self._list_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._list_ctrl.InsertColumn(0, _("Name"))
        self._list_ctrl.InsertColumn(1, _("Type"))
        self._list_ctrl.InsertColumn(2, _("Players"))
        main_sizer.Add(self._list_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        controls_row = wx.BoxSizer(wx.HORIZONTAL)
        self._add_button = wx.Button(self, label=_("Add"))
        self._configure_button = wx.Button(self, label=_("Configure players…"))
        self._remove_button = wx.Button(self, label=_("Remove"))
        controls_row.Add(self._add_button, 0, wx.ALL, 5)
        controls_row.Add(self._configure_button, 0, wx.ALL, 5)
        controls_row.Add(self._remove_button, 0, wx.ALL, 5)
        main_sizer.Add(controls_row, 0, wx.ALIGN_LEFT)

        move_row = wx.BoxSizer(wx.HORIZONTAL)
        self._up_button = wx.Button(self, label=_("Move up"))
        self._down_button = wx.Button(self, label=_("Move down"))
        move_row.Add(self._up_button, 0, wx.ALL, 5)
        move_row.Add(self._down_button, 0, wx.ALL, 5)
        main_sizer.Add(move_row, 0, wx.ALIGN_LEFT)

        action_sizer = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if action_sizer:
            main_sizer.Add(action_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self._add_button.Bind(wx.EVT_BUTTON, self._add_entry)
        self._remove_button.Bind(wx.EVT_BUTTON, self._remove_entry)
        self._configure_button.Bind(wx.EVT_BUTTON, self._configure_entry)
        self._up_button.Bind(wx.EVT_BUTTON, lambda _evt: self._move_entry(-1))
        self._down_button.Bind(wx.EVT_BUTTON, lambda _evt: self._move_entry(1))
        self._list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda _evt: self._update_button_states())
        self._list_ctrl.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda _evt: self._update_button_states())
        self._list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._handle_activate)

        self.SetSizer(main_sizer)
        self.SetSize((520, 420))
        self._refresh_list()

    def _selected_index(self) -> int:
        return self._list_ctrl.GetFirstSelected()

    def _selected_entry(self) -> dict[str, Any] | None:
        index = self._selected_index()
        if index == wx.NOT_FOUND or index >= len(self._entries):
            return None
        return self._entries[index]

    def _refresh_list(self, *, select_id: str | None = None) -> None:
        self._list_ctrl.DeleteAllItems()
        for entry in self._entries:
            index = self._list_ctrl.InsertItem(self._list_ctrl.GetItemCount(), entry["name"])
            kind_label = self.KIND_LABELS.get(entry["kind"], "")
            self._list_ctrl.SetItem(index, 1, kind_label)
            self._list_ctrl.SetItem(index, 2, self._format_slot_summary(entry.get("slots", [])))
            self._list_ctrl.SetItemData(index, index)
        for column in range(3):
            self._list_ctrl.SetColumnWidth(column, wx.LIST_AUTOSIZE_USEHEADER)

        selection_index = 0
        if select_id:
            for idx, entry in enumerate(self._entries):
                if entry["id"] == select_id:
                    selection_index = idx
                    break
        if self._entries:
            self._list_ctrl.Select(selection_index)
        self._update_button_states()

    def _update_button_states(self) -> None:
        selection = self._selected_index()
        can_modify = selection != wx.NOT_FOUND
        entry = self._entries[selection] if can_modify else None
        is_folder = bool(entry and entry.get("kind") == PlaylistKind.FOLDER)
        total = len(self._entries)
        self._remove_button.Enable(can_modify and total > 1)
        self._configure_button.Enable(can_modify and self._configure_callback is not None and not is_folder)
        self._up_button.Enable(can_modify and selection > 0)
        self._down_button.Enable(can_modify and selection != wx.NOT_FOUND and selection < total - 1)

    def _move_entry(self, offset: int) -> None:
        selection = self._selected_index()
        if selection == wx.NOT_FOUND:
            return
        target = selection + offset
        if target < 0 or target >= len(self._entries):
            return
        self._entries[selection], self._entries[target] = self._entries[target], self._entries[selection]
        self._refresh_list(select_id=self._entries[target]["id"])

    def _remove_entry(self, _event: wx.CommandEvent) -> None:
        selection = self._selected_index()
        if selection == wx.NOT_FOUND:
            return
        if len(self._entries) <= 1:
            wx.MessageBox(_("At least one playlist must remain."), _("Warning"), parent=self)
            return
        removed_entry = self._entries.pop(selection)
        self._removed.append(removed_entry["id"])
        next_selection = None
        if self._entries:
            next_index = min(selection, len(self._entries) - 1)
            next_selection = self._entries[next_index]["id"]
        self._refresh_list(select_id=next_selection)

    def _configure_entry(self, _event: wx.CommandEvent) -> None:
        if not self._configure_callback:
            return
        entry = self._selected_entry()
        if not entry:
            return
        slots = self._configure_callback(entry["id"])
        if slots is None:
            return
        entry["slots"] = list(slots)
        self._refresh_list(select_id=entry["id"])

    def _handle_activate(self, _event: wx.ListEvent) -> None:
        self._configure_entry(_event)

    def get_result(self) -> Optional[dict[str, list[str]]]:
        if not self._entries:
            return None
        return {
            "order": [entry["id"] for entry in self._entries],
            "removed": list(self._removed),
        }

    def _add_entry(self, _event: wx.CommandEvent) -> None:
        if not self._create_callback:
            return
        model = self._create_callback()
        if model is None:
            return
        self._entries.append(
            {"id": model.id, "name": model.name, "kind": model.kind, "slots": list(model.get_configured_slots())}
        )
        self._refresh_list(select_id=model.id)

    @staticmethod
    def _format_slot_summary(slots: list[str | None]) -> str:
        return str(sum(1 for slot in slots if slot))

