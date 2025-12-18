"""Panel managing a single playlist.

Kept in a dedicated subpackage to make `sara.ui.panels` easier to navigate.
"""

from __future__ import annotations

import wx

from typing import Callable

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistModel, PlaylistKind
from sara.core.hotkeys import HotkeyAction


class PlaylistPanel(wx.Panel):
    """Panel displayed in the layout representing one playlist."""

    def __init__(
        self,
        parent: wx.Window,
        model: PlaylistModel,
        on_focus: Callable[[str], None] | None = None,
        on_mix_configure: Callable[[str, str], None] | None = None,
        on_toggle_selection: Callable[[str, str], None] | None = None,
        on_selection_change: Callable[[str, list[int]], None] | None = None,
        on_play_request: Callable[[str, str], None] | None = None,
        swap_play_select: bool = False,
    ):
        super().__init__(parent)
        self.SetName(model.name)
        self.model = model
        self._on_focus = on_focus
        self._on_mix_configure = on_mix_configure
        self._on_toggle_selection = on_toggle_selection
        self._on_selection_change = on_selection_change
        self._on_play_request = on_play_request
        self._swap_play_select = bool(swap_play_select)
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
        # zachowaj selekcję/fokus, jeśli nie podano nowej selekcji
        if selected_indices is None:
            selected_indices = self.get_selected_indices()
            focused = self.get_focused_index()
        else:
            focused = -1

        self._refresh_content()

        if selected_indices:
            self.set_selection(selected_indices, focus=focus)
        elif focused != -1 and 0 <= focused < self._list_ctrl.GetItemCount():
            self._list_ctrl.Focus(focused)

    def _refresh_content(self) -> None:
        self._list_ctrl.DeleteAllItems()
        for index, item in enumerate(self.model.items):
            self._list_ctrl.InsertItem(index, self._display_title(item))
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
            self._list_ctrl.InsertItem(index, self._display_title(item))
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

    def _display_title(self, item: PlaylistItem) -> str:
        title = item.title
        if item.artist:
            title = f"{item.artist} - {title}"

        prefixes: list[str] = []
        if item.is_selected:
            prefixes.append(_("[selected]"))
        if item.has_loop() and (item.loop_enabled or getattr(item, "loop_auto_enabled", False)):
            prefixes.append(_("Loop"))
        if item.break_after:
            prefixes.append(_("Break"))

        if prefixes:
            return " ".join(prefixes) + " " + title
        return title

    def _status_label(self, item: PlaylistItem) -> str:
        label = _(item.status.value)
        extras = []
        if item.has_loop() and (item.loop_enabled or getattr(item, "loop_auto_enabled", False)):
            extras.append(_("loop"))
        if item.break_after:
            extras.append(_("break"))
        if extras:
            label += " (" + ", ".join(extras) + ")"
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

    def is_list_control(self, window: wx.Window | None) -> bool:
        return bool(window) and window is self._list_ctrl

    def get_selected_indices(self) -> list[int]:
        indices: list[int] = []
        index = self._list_ctrl.GetFirstSelected()
        while index != -1:
            indices.append(index)
            index = self._list_ctrl.GetNextItem(index, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
        return indices

    def get_focused_index(self) -> int:
        return self._list_ctrl.GetFocusedItem()

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

        if self._on_mix_configure:
            mix_id = wx.NewIdRef()
            menu.Append(mix_id, _("&Mix points…"))

            def _trigger_mix(_evt: wx.CommandEvent) -> None:
                self._notify_focus()
                self._on_mix_configure(self.model.id, item.id)

            self.Bind(wx.EVT_MENU, _trigger_mix, id=int(mix_id))

        if self._on_toggle_selection:
            toggle_id = wx.NewIdRef()
            toggle_label = _("&Select for playback") if not item.is_selected else _("Remove &selection")
            menu.Append(toggle_id, toggle_label)

            def _trigger_selection(_evt: wx.CommandEvent) -> None:
                self._notify_focus()
                self.set_selection([item_index], focus=True)
                self._list_ctrl.Focus(item_index)
                self._on_toggle_selection(self.model.id, item.id)

            self.Bind(wx.EVT_MENU, _trigger_selection, id=int(toggle_id))

        if not menu.GetMenuItemCount():
            event.Skip()
            menu.Destroy()
            return

        try:
            self.PopupMenu(menu)
        finally:
            menu.Destroy()

    def _handle_key_down(self, event: wx.KeyEvent) -> None:
        if self._handle_navigation_key(event):
            return
        if not self._handle_selection_key_event(event):
            event.Skip()

    def _handle_char_hook(self, event: wx.KeyEvent) -> None:
        if self._handle_navigation_key(event):
            return
        if not self._handle_selection_key_event(event):
            event.Skip()

    def _handle_char(self, event: wx.KeyEvent) -> None:
        if self._handle_navigation_key(event):
            return
        if not self._handle_selection_key_event(event):
            event.Skip()

    def _handle_list_key_down(self, event: wx.ListEvent) -> None:
        key_code = event.GetKeyCode()
        if key_code in (wx.WXK_UP, wx.WXK_DOWN) and not wx.GetKeyState(wx.WXK_SHIFT) and not wx.GetKeyState(wx.WXK_CONTROL) and not wx.GetKeyState(wx.WXK_ALT):
            delta = -1 if key_code == wx.WXK_UP else 1
            if self._move_focus_by_delta(delta):
                event.Skip(False)
                return
        if not self._handle_selection_key_event(event):
            event.Skip()

    def _handle_selection_key_event(self, event: wx.KeyEvent | wx.ListEvent) -> bool:
        key_code = event.GetKeyCode()
        allowed_keys = (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
        space_requested = (
            self._swap_play_select
            and self.model.kind is PlaylistKind.MUSIC
            and key_code == wx.WXK_SPACE
        )
        if not space_requested and key_code not in allowed_keys:
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

        item = self.model.items[index]

        if space_requested:
            if self._on_toggle_selection:
                # wymuś jednoznaczną selekcję na wskazanym elemencie
                self.set_selection([index], focus=True)
                self._trigger_selection_toggle(index)
                return True
            return False

        if self._swap_play_select and self.model.kind is PlaylistKind.MUSIC and self._on_play_request:
            self._notify_focus()
            self._list_ctrl.Focus(index)
            self._on_play_request(self.model.id, item.id)
            return True

        if not self._on_toggle_selection:
            return False

        self._trigger_selection_toggle(index)
        return True

    def _handle_item_activated(self, event: wx.ListEvent) -> None:
        if self._on_toggle_selection:
            self._trigger_selection_toggle(event.GetIndex())
        event.Skip()

    def _handle_navigation_key(self, event: wx.KeyEvent) -> bool:
        key_code = event.GetKeyCode()
        if key_code not in (wx.WXK_UP, wx.WXK_DOWN):
            return False
        if event.ControlDown() or event.AltDown() or event.MetaDown() or event.ShiftDown():
            return False
        delta = -1 if key_code == wx.WXK_UP else 1
        handled = self._move_focus_by_delta(delta)
        if handled:
            event.StopPropagation()
            event.Skip(False)
        return handled

    def _move_focus_by_delta(self, delta: int) -> bool:
        count = self._list_ctrl.GetItemCount()
        if count == 0:
            return False
        current = self._list_ctrl.GetFocusedItem()
        if current == wx.NOT_FOUND:
            selected = self.get_selected_indices()
            current = selected[0] if selected else 0
        target = max(0, min(count - 1, current + delta))
        if target == current:
            return True
        self.set_selection([target])
        self._list_ctrl.Focus(target)
        self._list_ctrl.EnsureVisible(target)
        return True

    def _suppress_tooltip(self, event: wx.Event) -> None:
        if hasattr(event, "SetToolTip"):
            event.SetToolTip(None)
        event.Skip(False)

    def _trigger_selection_toggle(self, index: int) -> None:
        if index < 0 or index >= len(self.model.items) or not self._on_toggle_selection:
            return
        item = self.model.items[index]
        self._notify_focus()
        self._list_ctrl.Focus(index)
        self._on_toggle_selection(self.model.id, item.id)

    def set_swap_play_select(self, enabled: bool) -> None:
        self._swap_play_select = bool(enabled)
