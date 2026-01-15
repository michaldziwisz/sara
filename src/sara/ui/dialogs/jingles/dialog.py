"""Dialog for managing the single jingle set (pages + 10 slots per page)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import wx

from sara.audio.engine import AudioEngine
from sara.core.i18n import gettext as _
from sara.core.media_metadata import extract_metadata
from sara.jingles import JingleSet, JinglePage, JingleSlot, ensure_page_count, save_jingle_set
from sara.ui.file_selection_dialog import FileSelectionDialog


_AUDIO_WILDCARD = _("Audio files|*.wav;*.mp3;*.mp2;*.mpg;*.mpeg;*.flac;*.ogg;*.m4a;*.aac;*.mp4|All files|*.*")


@dataclass
class JinglesDialogResult:
    device_id: str | None
    active_page_index: int


class JinglesDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window,
        *,
        audio_engine: AudioEngine,
        jingle_set: JingleSet,
        set_path: Path,
        active_page_index: int = 0,
        device_id: str | None = None,
    ) -> None:
        super().__init__(parent, title=_("Jingles"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._audio_engine = audio_engine
        self._set = jingle_set
        ensure_page_count(self._set, 1)
        self._set_path = set_path
        self._active_page_index = max(0, int(active_page_index))
        self._device_id = device_id

        self._pages_list = wx.ListBox(self)
        self._page_name = wx.TextCtrl(self)

        self._slot_label_ctrls: list[wx.TextCtrl] = []
        self._slot_path_ctrls: list[wx.TextCtrl] = []
        self._slot_browse_buttons: list[wx.Button] = []
        self._slot_clear_buttons: list[wx.Button] = []

        self._device_choice = wx.Choice(self)
        self._device_entries: list[tuple[str | None, str]] = [(None, _("(default)"))]

        self._btn_add_page = wx.Button(self, label=_("Add page"))
        self._btn_remove_page = wx.Button(self, label=_("Remove page"))

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        top_row = wx.BoxSizer(wx.HORIZONTAL)
        top_row.Add(wx.StaticText(self, label=_("Pages:")), 0, wx.ALIGN_TOP | wx.RIGHT, 8)
        top_row.Add(self._pages_list, 0, wx.EXPAND | wx.RIGHT, 10)

        right = wx.BoxSizer(wx.VERTICAL)
        name_row = wx.BoxSizer(wx.HORIZONTAL)
        name_row.Add(wx.StaticText(self, label=_("Page name:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        name_row.Add(self._page_name, 1)
        right.Add(name_row, 0, wx.EXPAND | wx.BOTTOM, 8)

        grid = wx.FlexGridSizer(rows=10, cols=5, vgap=4, hgap=6)
        grid.AddGrowableCol(2, 1)  # path

        for idx in range(10):
            slot_num = idx + 1 if idx < 9 else 0
            grid.Add(wx.StaticText(self, label=str(slot_num)), 0, wx.ALIGN_CENTER_VERTICAL)
            label_ctrl = wx.TextCtrl(self)
            path_ctrl = wx.TextCtrl(self, style=wx.TE_READONLY)
            label_ctrl.SetName(_("Jingle slot %s label") % slot_num)
            path_ctrl.SetName(_("Jingle slot %s file") % slot_num)
            browse = wx.Button(self, label=_("Browse…"))
            clear = wx.Button(self, label=_("Clear"))
            self._slot_label_ctrls.append(label_ctrl)
            self._slot_path_ctrls.append(path_ctrl)
            self._slot_browse_buttons.append(browse)
            self._slot_clear_buttons.append(clear)

            grid.Add(label_ctrl, 0, wx.EXPAND)
            grid.Add(path_ctrl, 0, wx.EXPAND)
            grid.Add(browse, 0)
            grid.Add(clear, 0)

        right.Add(wx.StaticText(self, label=_("Slots (label + file):")), 0, wx.BOTTOM, 4)
        right.Add(grid, 1, wx.EXPAND | wx.BOTTOM, 10)

        device_row = wx.BoxSizer(wx.HORIZONTAL)
        device_row.Add(wx.StaticText(self, label=_("Jingle device:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        device_row.Add(self._device_choice, 1)
        right.Add(device_row, 0, wx.EXPAND)

        top_row.Add(right, 1, wx.EXPAND)
        main_sizer.Add(top_row, 1, wx.EXPAND | wx.ALL, 10)

        page_btns = wx.BoxSizer(wx.HORIZONTAL)
        page_btns.Add(self._btn_add_page, 0, wx.RIGHT, 6)
        page_btns.Add(self._btn_remove_page, 0)
        main_sizer.Add(page_btns, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        button_sizer = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if button_sizer:
            main_sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 10)

        self.SetSizer(main_sizer)
        self.SetSize((900, 520))
        self.CentreOnParent()

        self._pages_list.Bind(wx.EVT_LISTBOX, self._on_select_page)
        self._btn_add_page.Bind(wx.EVT_BUTTON, self._on_add_page)
        self._btn_remove_page.Bind(wx.EVT_BUTTON, self._on_remove_page)
        self._page_name.Bind(wx.EVT_TEXT, self._on_page_name_change)
        for idx in range(10):
            self._slot_label_ctrls[idx].Bind(wx.EVT_TEXT, lambda _evt, i=idx: self._on_slot_change(i))
            self._slot_browse_buttons[idx].Bind(wx.EVT_BUTTON, lambda _evt, i=idx: self._browse_slot(i))
            self._slot_clear_buttons[idx].Bind(wx.EVT_BUTTON, lambda _evt, i=idx: self._clear_slot(i))
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

        self._refresh_pages()
        self._populate_devices()
        self._select_page(self._active_page_index)

    def get_result(self) -> JinglesDialogResult:
        return JinglesDialogResult(device_id=self._selected_device_id(), active_page_index=self._pages_list.GetSelection())

    def _pages(self) -> list[JinglePage]:
        ensure_page_count(self._set, 1)
        return self._set.normalized_pages()

    def _page(self) -> JinglePage:
        idx = max(0, self._pages_list.GetSelection())
        pages = self._pages()
        if idx >= len(pages):
            idx = 0
        return pages[idx]

    def _select_page(self, index: int) -> None:
        pages = self._pages()
        if not pages:
            return
        idx = max(0, min(int(index), len(pages) - 1))
        self._pages_list.SetSelection(idx)
        self._load_page_into_controls()
        self._update_page_buttons()

    def _refresh_pages(self) -> None:
        self._pages_list.Clear()
        for idx, page in enumerate(self._pages(), start=1):
            label = str(page.name) if page.name else _("Page %d") % idx
            self._pages_list.Append(label)
        if self._pages_list.GetCount() > 0 and self._pages_list.GetSelection() == wx.NOT_FOUND:
            self._pages_list.SetSelection(0)
        self._update_page_buttons()

    def _update_page_buttons(self) -> None:
        self._btn_remove_page.Enable(self._pages_list.GetCount() > 1)

    def _load_page_into_controls(self) -> None:
        page = self._page()
        self._page_name.ChangeValue(str(page.name or ""))
        slots = page.normalized_slots()
        for idx, slot in enumerate(slots):
            derived_label = ""
            if slot.label:
                derived_label = str(slot.label)
            elif slot.path:
                try:
                    derived_label = Path(slot.path).stem
                except Exception:
                    derived_label = str(slot.path)
            self._slot_label_ctrls[idx].ChangeValue(derived_label)
            self._slot_path_ctrls[idx].ChangeValue(str(slot.path) if slot.path else "")

    def _on_select_page(self, _evt: wx.CommandEvent) -> None:
        self._load_page_into_controls()
        self._update_page_buttons()

    def _on_add_page(self, _evt: wx.CommandEvent) -> None:
        pages = self._pages()
        pages.append(JinglePage())
        self._set.pages = pages
        self._refresh_pages()
        self._select_page(len(pages) - 1)

    def _on_remove_page(self, _evt: wx.CommandEvent) -> None:
        pages = self._pages()
        if len(pages) <= 1:
            return
        idx = max(0, self._pages_list.GetSelection())
        idx = min(idx, len(pages) - 1)
        del pages[idx]
        self._set.pages = pages
        self._refresh_pages()
        self._select_page(min(idx, len(pages) - 1))

    def _on_page_name_change(self, _evt: wx.CommandEvent) -> None:
        page = self._page()
        value = self._page_name.GetValue().strip()
        page.name = value or None
        self._refresh_pages()

    def _on_slot_change(self, idx: int) -> None:
        page = self._page()
        slots = page.normalized_slots()
        slots[idx].label = self._slot_label_ctrls[idx].GetValue().strip() or None
        page.slots = slots

    def _browse_slot(self, idx: int) -> None:
        dialog = FileSelectionDialog(
            self,
            title=_("Select audio file"),
            wildcard=_AUDIO_WILDCARD,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            paths = dialog.get_paths()
        finally:
            dialog.Destroy()
        if not paths:
            return
        selected = Path(paths[0])
        if not selected.exists() or not selected.is_file():
            wx.MessageBox(_("Selected path is not a file."), _("Error"), parent=self)
            return
        page = self._page()
        slots = page.normalized_slots()
        slots[idx].path = selected
        try:
            slots[idx].replay_gain_db = extract_metadata(selected).replay_gain_db
        except Exception:
            slots[idx].replay_gain_db = None
        if not (self._slot_label_ctrls[idx].GetValue() or "").strip():
            slots[idx].label = selected.stem
            self._slot_label_ctrls[idx].ChangeValue(selected.stem)
        page.slots = slots
        self._slot_path_ctrls[idx].ChangeValue(str(selected))

    def _clear_slot(self, idx: int) -> None:
        page = self._page()
        slots = page.normalized_slots()
        slots[idx] = JingleSlot()
        page.slots = slots
        self._slot_label_ctrls[idx].ChangeValue("")
        self._slot_path_ctrls[idx].ChangeValue("")

    def _populate_devices(self) -> None:
        devices = self._audio_engine.get_devices()
        entries: list[tuple[str | None, str]] = [(None, _("(default)"))]
        entries.extend((device.id, device.name) for device in devices)
        self._device_entries = entries
        self._device_choice.Clear()
        for _device_id, label in entries:
            self._device_choice.Append(label)

        current = self._device_id
        selection = 0
        if current:
            for idx, (device_id, _label) in enumerate(entries):
                if device_id == current:
                    selection = idx
                    break
        if entries:
            self._device_choice.SetSelection(selection)

    def _selected_device_id(self) -> str | None:
        idx = self._device_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            return None
        if idx < 0 or idx >= len(self._device_entries):
            return None
        return self._device_entries[idx][0]

    def _on_ok(self, _evt: wx.CommandEvent) -> None:
        try:
            save_jingle_set(self._set_path, self._set)
        except Exception as exc:  # pylint: disable=broad-except
            wx.MessageBox(_("Failed to save jingles: %s") % exc, _("Error"), parent=self)
            return
        self.EndModal(wx.ID_OK)
