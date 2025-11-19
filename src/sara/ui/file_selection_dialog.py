"""Custom cross-platform file selection dialog with keyboard-friendly navigation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import wx

from sara.core.i18n import gettext as _
from sara.ui.file_browser import FileBrowser, FileEntry


def parse_file_wildcard(wildcard: str) -> list[tuple[str, list[str]]]:
    parts = [part for part in wildcard.split("|") if part]
    if len(parts) < 2:
        return [( _("All files"), ["*.*"])]
    filters: list[tuple[str, list[str]]] = []
    for i in range(0, len(parts) - 1, 2):
        desc = parts[i].strip() or _("Files")
        pattern = parts[i + 1].strip() or "*.*"
        filters.append((desc, [p.strip() for p in pattern.split(";") if p.strip()]))
    return filters or [( _("All files"), ["*.*"])]


def ensure_save_selection(current_path: Path | None, name_value: str | None) -> list[str]:
    name = (name_value or "").strip()
    if not name:
        raise ValueError(_("Enter a file name."))
    target_dir = current_path or Path.cwd()
    return [str(target_dir / name)]


class FileSelectionDialog(wx.Dialog):
    _last_path: Path | None = None

    """Minimal file picker that avoids native dialogs but keeps familiar workflow."""

    def __init__(
        self,
        parent: wx.Window | None,
        *,
        title: str,
        wildcard: str = _("All files|*.*"),
        style: int = wx.FD_OPEN,
        message: str | None = None,
        start_path: Path | None = None,
        file_browser: FileBrowser | None = None,
    ) -> None:
        super().__init__(parent, title=title or _("Select files"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._style = style
        self._allow_multiple = bool(style & wx.FD_MULTIPLE)
        self._save_mode = bool(style & wx.FD_SAVE)
        self._require_existing = bool(style & wx.FD_FILE_MUST_EXIST)
        self._prompt_overwrite = bool(style & wx.FD_OVERWRITE_PROMPT)
        self._filters = parse_file_wildcard(wildcard)
        self._filter_choice: wx.Choice | None = None
        initial_path = start_path or FileSelectionDialog._last_path
        self._browser = file_browser or FileBrowser(initial_path)
        self._entries: list[FileEntry] = []
        self._selected_paths: list[str] = []

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        if message:
            info = wx.StaticText(self, label=message)
            main_sizer.Add(info, 0, wx.ALL, 5)

        path_sizer = wx.BoxSizer(wx.HORIZONTAL)
        path_sizer.Add(wx.StaticText(self, label=_("Location:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self._path_label = wx.StaticText(self, label="")
        path_sizer.Add(self._path_label, 1, wx.ALIGN_CENTER_VERTICAL)
        main_sizer.Add(path_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

        filter_names = [desc for desc, _pattern in self._filters]
        if len(filter_names) > 1:
            filter_sizer = wx.BoxSizer(wx.HORIZONTAL)
            filter_sizer.Add(wx.StaticText(self, label=_("Filter:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            self._filter_choice = wx.Choice(self, choices=filter_names)
            self._filter_choice.SetSelection(0)
            self._filter_choice.Bind(wx.EVT_CHOICE, self._on_filter_change)
            filter_sizer.Add(self._filter_choice, 0)
            main_sizer.Add(filter_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

        list_style = wx.LC_REPORT | wx.BORDER_SIMPLE
        if not self._allow_multiple:
            list_style |= wx.LC_SINGLE_SEL
        self._list_ctrl = wx.ListCtrl(self, style=list_style)
        self._list_ctrl.InsertColumn(0, _("Name"), width=320)
        self._list_ctrl.InsertColumn(1, _("Type"), width=120)
        self._list_ctrl.InsertColumn(2, _("Size"), format=wx.LIST_FORMAT_RIGHT, width=100)
        self._list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_item_activated)
        self._list_ctrl.Bind(wx.EVT_CHAR_HOOK, self._on_list_char)
        main_sizer.Add(self._list_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        self._name_input: wx.TextCtrl | None = None
        if self._save_mode:
            name_sizer = wx.BoxSizer(wx.HORIZONTAL)
            name_sizer.Add(wx.StaticText(self, label=_("File name:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            self._name_input = wx.TextCtrl(self)
            name_sizer.Add(self._name_input, 1)
            main_sizer.Add(name_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        button_sizer = wx.StdDialogButtonSizer()
        self._ok_button = wx.Button(self, wx.ID_OK)
        cancel_button = wx.Button(self, wx.ID_CANCEL)
        button_sizer.AddButton(self._ok_button)
        button_sizer.AddButton(cancel_button)
        button_sizer.Realize()
        main_sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 5)
        self.SetSizerAndFit(main_sizer)
        self.SetSizeHints(600, 400)
        self.CentreOnParent()

        self.Bind(wx.EVT_BUTTON, self._on_confirm, id=wx.ID_OK)
        wx.CallAfter(self._list_ctrl.SetFocus)
        self._refresh_entries()

    # ------------------------------------------------------------------ helpers
    def _active_patterns(self) -> list[str]:
        index = 0
        if self._filter_choice is not None:
            index = max(0, self._filter_choice.GetSelection())
        if index >= len(self._filters):
            index = 0
        return self._filters[index][1]

    def _on_filter_change(self, _event: wx.CommandEvent) -> None:
        self._refresh_entries()

    def _refresh_entries(self) -> None:
        patterns = self._active_patterns()
        entries = self._browser.list_entries(patterns)
        self._entries = entries
        current_path = self._browser.current_path()
        path_text = str(current_path) if current_path else _("Computer")
        self._path_label.SetLabel(path_text)
        self._list_ctrl.DeleteAllItems()
        for index, entry in enumerate(entries):
            item = self._list_ctrl.InsertItem(index, entry.name)
            entry_type = entry.kind
            if entry_type == "file":
                entry_label = _("File")
            elif entry_type == "dir":
                entry_label = _("Folder")
            elif entry_type == "drive":
                entry_label = _("Drive")
            else:
                entry_label = _("Parent folder")
            self._list_ctrl.SetItem(index, 1, entry_label)
            if entry_type == "file":
                self._list_ctrl.SetItem(index, 2, entry.size_label)
        if entries:
            self._list_ctrl.Focus(0)

    # ----------------------------------------------------------------- events
    def _on_list_char(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == wx.WXK_BACK:
            self._go_up()
            return
        if code == wx.WXK_RETURN:
            if self._activate_focus_or_confirm():
                return
        event.Skip()

    def _activate_focus_or_confirm(self) -> bool:
        index = self._list_ctrl.GetFocusedItem()
        if index == -1:
            return self._confirm_selection()
        entry = self._entries[index] if 0 <= index < len(self._entries) else None
        if entry and entry["type"] == "file":
            return self._confirm_selection()
        self._activate_entry(index)
        return True

    def _go_up(self) -> None:
        self._browser.go_up()
        self._refresh_entries()

    def _on_item_activated(self, event: wx.ListEvent) -> None:
        self._activate_entry(event.GetIndex())

    def _activate_entry(self, index: int) -> None:
        if index < 0 or index >= len(self._entries):
            return
        entry = self._entries[index]
        entry_type = entry.kind
        if entry_type in ("dir", "drive"):
            self._browser.set_current_path(entry.path)
            self._refresh_entries()
        elif entry_type == "parent":
            self._browser.set_current_path(entry.path)
            self._refresh_entries()
        elif entry_type == "file":
            self._confirm_selection()

    def _on_confirm(self, _event: wx.CommandEvent) -> None:
        if not self._confirm_selection():
            return

    def _confirm_selection(self) -> bool:
        selected = self._gather_selected_files()
        if self._save_mode:
            if not selected:
                try:
                    selected = ensure_save_selection(
                        self._browser.current_path(),
                        self._name_input.GetValue() if self._name_input else "",
                    )
                except ValueError as exc:
                    wx.MessageBox(str(exc), _("Warning"), parent=self)
                    return False
            if self._prompt_overwrite and any(Path(path).exists() for path in selected):
                response = wx.MessageBox(
                    _("File exists. Overwrite?"),
                    _("Confirm overwrite"),
                    parent=self,
                    style=wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
                )
                if response != wx.YES:
                    return False
        else:
            if not selected:
                wx.MessageBox(_("Select at least one file."), _("Warning"), parent=self)
                return False
            if self._require_existing and not all(Path(path).exists() for path in selected):
                wx.MessageBox(_("Some files do not exist."), _("Warning"), parent=self)
                return False

        self._selected_paths = selected
        if selected:
            last_dir = Path(selected[0]).parent
            FileSelectionDialog._last_path = last_dir
        else:
            current_path = self._browser.current_path()
            if current_path:
                FileSelectionDialog._last_path = current_path
        self.EndModal(wx.ID_OK)
        return True

    def _gather_selected_files(self) -> list[str]:
        indices: list[int] = []
        index = self._list_ctrl.GetFirstSelected()
        while index != -1:
            indices.append(index)
            index = self._list_ctrl.GetNextItem(index, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
        files: list[str] = []
        for idx in indices:
            if 0 <= idx < len(self._entries):
                entry = self._entries[idx]
                if entry.kind == "file":
                    files.append(str(entry.path))
        return files

    # ------------------------------------------------------------- public API
    def get_paths(self) -> list[str]:
        if self._selected_paths:
            return list(self._selected_paths)
        return self._gather_selected_files()

    def get_path(self) -> str:
        paths = self.get_paths()
        return paths[0] if paths else ""
