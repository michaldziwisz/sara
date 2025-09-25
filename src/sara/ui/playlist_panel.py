"""Panel managing a single playlist."""

from __future__ import annotations

import wx

from typing import Callable

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistModel
from sara.core.hotkeys import HotkeyAction


class PlaylistPanel(wx.Panel):
    """Panel displayed in the layout representing one playlist."""

    def __init__(
        self,
        parent: wx.Window,
        model: PlaylistModel,
        on_focus: Callable[[str], None] | None = None,
        on_loop_configure: Callable[[str, str], None] | None = None,
        on_set_marker: Callable[[str, str], None] | None = None,
        on_selection_change: Callable[[str, list[int]], None] | None = None,
    ):
        super().__init__(parent)
        self.SetName(model.name)
        self.model = model
        self._on_focus = on_focus
        self._on_loop_configure = on_loop_configure
        self._on_set_marker = on_set_marker
        self._on_selection_change = on_selection_change
        self._active = False
        self._base_accessible_name = model.name
        self._list_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT)
        self._list_ctrl.SetName(self._base_accessible_name)
        self._list_ctrl.SetLabel(self._base_accessible_name)
        self._list_ctrl.SetToolTip(None)
        self.SetToolTip(None)
        self._list_ctrl.InsertColumn(0, _("Title"))
        self._list_ctrl.InsertColumn(1, _("Duration"))
        self._list_ctrl.InsertColumn(2, _("Status"))
        self._list_ctrl.InsertColumn(3, _("Progress"))
        for index in range(4):
            self._list_ctrl.SetColumnWidth(index, wx.LIST_AUTOSIZE_USEHEADER)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._list_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)

        self._register_hotkeys()
        self.Bind(wx.EVT_CHILD_FOCUS, self._handle_child_focus)
        self._list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self._handle_list_interaction)
        self._list_ctrl.Bind(wx.EVT_LEFT_DOWN, self._handle_list_interaction)
        self._list_ctrl.Bind(wx.EVT_CONTEXT_MENU, self._show_context_menu)
        self._list_ctrl.Bind(wx.EVT_KEY_DOWN, self._handle_key_down)
        self._list_ctrl.Bind(wx.EVT_CHAR_HOOK, self._handle_char_hook)
        self._list_ctrl.Bind(wx.EVT_CHAR, self._handle_char)
        self._list_ctrl.Bind(wx.EVT_LIST_KEY_DOWN, self._handle_list_key_down)
        self._list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._handle_item_activated)
        tooltip_event = getattr(wx, "EVT_LIST_ITEM_GETTOOLTIP", None)
        if tooltip_event is not None:
            self._list_ctrl.Bind(tooltip_event, self._suppress_tooltip)
        self._refresh_content()
        self.set_active(False)

    def _notify_focus(self) -> None:
        if self._on_focus:
            self._on_focus(self.model.id)

    def _handle_child_focus(self, event: wx.ChildFocusEvent) -> None:
        self._notify_focus()
        event.Skip()

    def _handle_list_interaction(self, event: wx.Event) -> None:
        self._notify_focus()
        self._notify_selection_change()
        event.Skip()

    def _notify_selection_change(self) -> None:
        if self._on_selection_change:
            self._on_selection_change(self.model.id, self.get_selected_indices())

    def _register_hotkeys(self) -> None:
        # TODO: powiązać skróty z akcjami (play/pause/stop/fade)
        self.model.hotkeys.setdefault("play", HotkeyAction("F1"))

    def refresh(self, selected_indices: list[int] | None = None, *, focus: bool = True) -> None:
        self._refresh_content()
        if selected_indices is not None:
            self.set_selection(selected_indices, focus=focus)

    def _refresh_content(self) -> None:
        self._list_ctrl.DeleteAllItems()
        for index, item in enumerate(self.model.items):
            self._list_ctrl.InsertItem(index, item.title)
            self._list_ctrl.SetItem(index, 1, item.duration_display)
            self._list_ctrl.SetItem(index, 2, self._status_label(item))
            self._list_ctrl.SetItem(index, 3, item.progress_display)

    def mark_item_status(self, item_id: str, status: PlaylistItemStatus) -> None:
        for index, item in enumerate(self.model.items):
            if item.id == item_id:
                self._list_ctrl.SetItem(index, 2, self._status_label(item))
                self._list_ctrl.SetItem(index, 3, item.progress_display)
                break

    def append_items(self, items: list[PlaylistItem]) -> None:
        self.model.add_items(items)
        current_count = self._list_ctrl.GetItemCount()
        for item in items:
            index = current_count
            self._list_ctrl.InsertItem(index, item.title)
            self._list_ctrl.SetItem(index, 1, item.duration_display)
            self._list_ctrl.SetItem(index, 2, item.status.value)
            self._list_ctrl.SetItem(index, 3, item.progress_display)
            current_count += 1

    def update_progress(self, item_id: str) -> None:
        for index, item in enumerate(self.model.items):
            if item.id == item_id:
                self._list_ctrl.SetItem(index, 3, item.progress_display)
                if item.status is PlaylistItemStatus.PLAYING:
                    self._list_ctrl.SetItem(index, 2, self._status_label(item))
                break

    def _status_label(self, item: PlaylistItem) -> str:
        label = _(item.status.value)
        if item.has_loop():
            label += _(" (loop)")
        if item.is_marker:
            label += _(" [marker]")
        return label

    def set_active(self, active: bool) -> None:
        self._active = active
        accessible_name = self._base_accessible_name
        self._list_ctrl.SetName(accessible_name)
        self._list_ctrl.SetLabel(accessible_name)
        self._list_ctrl.UnsetToolTip()

    def focus_list(self) -> None:
        self._list_ctrl.SetFocus()
        if self._list_ctrl.GetItemCount() > 0 and self._list_ctrl.GetFirstSelected() == -1:
            self._list_ctrl.Focus(0)

    def get_selected_indices(self) -> list[int]:
        indices: list[int] = []
        index = self._list_ctrl.GetFirstSelected()
        while index != -1:
            indices.append(index)
            index = self._list_ctrl.GetNextItem(index, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
        return indices

    def set_selection(self, indices: list[int], *, focus: bool = True) -> None:
        count = self._list_ctrl.GetItemCount()
        valid_indices = [index for index in indices if 0 <= index < count]
        self._list_ctrl.Freeze()
        try:
            current = set(self.get_selected_indices())
            for index in current:
                if index not in valid_indices:
                    self._list_ctrl.Select(index, False)
            for index in valid_indices:
                self._list_ctrl.Select(index)
            if focus and valid_indices:
                self._list_ctrl.Focus(valid_indices[0])
        finally:
            self._list_ctrl.Thaw()

    def select_index(self, index: int, *, focus: bool = True) -> None:
        self.set_selection([index], focus=focus)

    def _show_context_menu(self, event: wx.ContextMenuEvent) -> None:
        item_index = self._list_ctrl.GetFocusedItem()
        if item_index == wx.NOT_FOUND and self._list_ctrl.GetItemCount() > 0:
            item_index = 0
        if item_index == wx.NOT_FOUND:
            event.Skip()
            return

        item = self.model.items[item_index]
        menu = wx.Menu()

        if self._on_loop_configure:
            loop_id = wx.NewIdRef()
            label = _("&Loop…")
            if item.has_loop():
                label = _("&Loop… (set)")
            menu.Append(loop_id, label)

            def _trigger_loop(_evt: wx.CommandEvent) -> None:
                self._notify_focus()
                self._on_loop_configure(self.model.id, item.id)

            self.Bind(wx.EVT_MENU, _trigger_loop, id=int(loop_id))

        if self._on_set_marker:
            marker_id = wx.NewIdRef()
            marker_label = _("&Set marker") if not item.is_marker else _("Remove &marker")
            menu.Append(marker_id, marker_label)

            def _trigger_marker(_evt: wx.CommandEvent) -> None:
                self._notify_focus()
                self._on_set_marker(self.model.id, item.id)

            self.Bind(wx.EVT_MENU, _trigger_marker, id=int(marker_id))

        if not menu.GetMenuItemCount():
            event.Skip()
            return

        self.PopupMenu(menu)
        menu.Destroy()

    def _handle_key_down(self, event: wx.KeyEvent) -> None:
        if not self._handle_marker_event(event):
            event.Skip()

    def _handle_char_hook(self, event: wx.KeyEvent) -> None:
        if not self._handle_marker_event(event):
            event.Skip()

    def _handle_char(self, event: wx.KeyEvent) -> None:
        if not self._handle_marker_event(event):
            event.Skip()

    def _handle_list_key_down(self, event: wx.ListEvent) -> None:
        if not self._handle_marker_event(event):
            event.Skip()

    def _handle_marker_event(self, event: wx.KeyEvent | wx.ListEvent) -> bool:
        key_code = event.GetKeyCode()
        if key_code not in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            return False
        if not self._on_set_marker:
            return False
        if isinstance(event, wx.KeyEvent):
            if event.ControlDown() or event.AltDown() or event.MetaDown():
                return False
            if event.ShiftDown():
                return False

        index = self._list_ctrl.GetFocusedItem()
        if index == wx.NOT_FOUND:
            index = self._list_ctrl.GetFirstSelected()
        if index == wx.NOT_FOUND and self._list_ctrl.GetItemCount() > 0:
            index = 0

        if index == wx.NOT_FOUND or index >= len(self.model.items):
            return False

        self._trigger_marker(index)
        return True

    def _handle_item_activated(self, event: wx.ListEvent) -> None:
        if self._on_set_marker:
            self._trigger_marker(event.GetIndex())
        event.Skip()

    def _suppress_tooltip(self, event: wx.Event) -> None:
        if hasattr(event, "SetToolTip"):
            event.SetToolTip(None)
        event.Skip(False)

    def _trigger_marker(self, index: int) -> None:
        if index < 0 or index >= len(self.model.items) or not self._on_set_marker:
            return
        item = self.model.items[index]
        self._notify_focus()
        self._on_set_marker(self.model.id, item.id)
