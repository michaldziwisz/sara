"""Keyboard shortcut editor dialog."""

from __future__ import annotations

from typing import Dict, Tuple

import wx

from sara.core.i18n import gettext as _
from sara.core.shortcuts import ShortcutDescriptor, iter_shortcuts
from sara.core.config import SettingsManager
from sara.ui.shortcut_capture_dialog import ShortcutCaptureDialog
from sara.ui.shortcut_utils import format_shortcut_display

_SCOPE_LABELS = {
    "global": "Global",
    "playlist": "Playlist",
    "edit": "Edit",
    "playlist_menu": "Playlist menu",
}


class ShortcutEditorDialog(wx.Dialog):
    """Allow the user to review and modify keyboard shortcuts."""

    def __init__(self, parent: wx.Window, *, settings: SettingsManager) -> None:
        super().__init__(parent, title=_("Keyboard shortcuts"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._settings = settings
        self._descriptors = sorted(iter_shortcuts(), key=lambda d: (d.scope, d.label))
        self._values: Dict[Tuple[str, str], str] = {}
        for descriptor in self._descriptors:
            value = self._settings.get_shortcut(descriptor.scope, descriptor.action)
            if not value:
                value = descriptor.default
            self._values[(descriptor.scope, descriptor.action)] = value

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        self._list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._list.InsertColumn(0, _("Scope"), width=140)
        self._list.InsertColumn(1, _("Action"), width=260)
        self._list.InsertColumn(2, _("Shortcut"), width=160)
        main_sizer.Add(self._list, 1, wx.EXPAND | wx.ALL, 10)

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        self._change_button = wx.Button(self, label=_("Change…"))
        self._restore_button = wx.Button(self, label=_("Restore default"))
        button_row.Add(self._change_button, 0, wx.RIGHT, 5)
        button_row.Add(self._restore_button, 0)
        main_sizer.Add(button_row, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.LEFT | wx.BOTTOM, 10)

        button_sizer = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if button_sizer:
            main_sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 10)

        self.SetSizerAndFit(main_sizer)
        self.SetMinSize((560, 420))
        self._populate()
        self._update_buttons()

        self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_selection_change)
        self._list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_selection_change)
        self._change_button.Bind(wx.EVT_BUTTON, self._on_change)
        self._restore_button.Bind(wx.EVT_BUTTON, self._on_restore)

    def _populate(self) -> None:
        self._list.DeleteAllItems()
        for index, descriptor in enumerate(self._descriptors):
            scope_label = _(_SCOPE_LABELS.get(descriptor.scope, descriptor.scope.title()))
            self._list.InsertItem(index, scope_label)
            self._list.SetItem(index, 1, descriptor.label)
            shortcut = self._values[(descriptor.scope, descriptor.action)]
            self._list.SetItem(index, 2, format_shortcut_display(shortcut))

    def _selected_index(self) -> int:
        return self._list.GetFirstSelected()

    def _selected_descriptor(self) -> ShortcutDescriptor | None:
        index = self._selected_index()
        if index == wx.NOT_FOUND:
            return None
        return self._descriptors[index]

    def _on_selection_change(self, _event: wx.Event) -> None:
        self._update_buttons()

    def _update_buttons(self) -> None:
        has_selection = self._selected_index() != wx.NOT_FOUND
        self._change_button.Enable(has_selection)
        self._restore_button.Enable(has_selection)

    def _on_change(self, _event: wx.CommandEvent) -> None:
        descriptor = self._selected_descriptor()
        if descriptor is None:
            return
        dialog = ShortcutCaptureDialog(self)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        new_shortcut = dialog.get_shortcut()
        dialog.Destroy()
        if not new_shortcut:
            return
        if self._is_duplicate(descriptor.scope, descriptor.action, new_shortcut):
            wx.MessageBox(_("This shortcut is already assigned to another action."), _("Error"), parent=self)
            return
        self._values[(descriptor.scope, descriptor.action)] = new_shortcut
        self._update_row(descriptor)

    def _on_restore(self, _event: wx.CommandEvent) -> None:
        descriptor = self._selected_descriptor()
        if descriptor is None:
            return
        self._values[(descriptor.scope, descriptor.action)] = descriptor.default
        self._update_row(descriptor)

    def _update_row(self, descriptor: ShortcutDescriptor) -> None:
        index = self._descriptors.index(descriptor)
        shortcut = self._values[(descriptor.scope, descriptor.action)]
        self._list.SetItem(index, 2, format_shortcut_display(shortcut))

    def _is_duplicate(self, scope: str, action: str, shortcut: str) -> bool:
        if not shortcut:
            return False
        normalized = shortcut.upper()
        for (other_scope, other_action), value in self._values.items():
            if (other_scope, other_action) == (scope, action):
                continue
            if value.upper() == normalized and normalized:
                return True
        return False

    def get_values(self) -> Dict[Tuple[str, str], str]:
        return dict(self._values)
