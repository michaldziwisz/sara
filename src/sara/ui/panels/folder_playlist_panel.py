"""Playlist panel specialized for quick-access music folders."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

import wx

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistModel
from .playlist_panel import PlaylistPanel


class FolderPlaylistPanel(PlaylistPanel):
    """Playlist panel that previews on space and sends tracks to music playlists."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        model: PlaylistModel,
        on_focus: Callable[[str], None] | None,
        on_selection_change: Callable[[str, list[int]], None] | None,
        on_mix_configure: Callable[[str, str], None] | None,
        on_preview_request: Callable[[str, str], None] | None,
        on_send_to_music: Callable[[str, Sequence[str]], None] | None,
        on_select_folder: Callable[[str], None] | None,
        on_reload_folder: Callable[[str], None] | None,
    ) -> None:
        super().__init__(
            parent,
            model=model,
            on_focus=on_focus,
            on_mix_configure=on_mix_configure,
            on_toggle_selection=None,
            on_selection_change=on_selection_change,
            on_play_request=None,
            swap_play_select=False,
        )
        self._on_preview_request = on_preview_request
        self._on_send_to_music = on_send_to_music
        self._on_select_folder = on_select_folder
        self._on_reload_folder = on_reload_folder
        self._folder_path: Path | None = model.folder_path

        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        self._folder_label = wx.StaticText(self, label=_("No folder selected"))
        toolbar.Add(self._folder_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self._select_button = wx.Button(self, label=_("Select folder…"))
        self._reload_button = wx.Button(self, label=_("Reload"))
        toolbar.Add(self._select_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        toolbar.Add(self._reload_button, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer = self.GetSizer()
        sizer.Insert(0, toolbar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

        self._select_button.Bind(wx.EVT_BUTTON, lambda _evt: self._handle_select_folder())
        self._reload_button.Bind(wx.EVT_BUTTON, lambda _evt: self._handle_reload_folder())
        self.set_folder_path(model.folder_path)

    def set_folder_path(self, folder_path: Path | None) -> None:
        """Update label/buttons to reflect the configured folder."""
        self._folder_path = folder_path
        if folder_path:
            self._folder_label.SetLabel(str(folder_path))
            self._reload_button.Enable(True)
        else:
            self._folder_label.SetLabel(_("No folder selected"))
            self._reload_button.Enable(False)
        self.Layout()

    def _handle_select_folder(self) -> None:
        if self._on_select_folder:
            self._on_select_folder(self.model.id)

    def _handle_reload_folder(self) -> None:
        if self._on_reload_folder:
            self._on_reload_folder(self.model.id)

    def _handle_selection_key_event(self, event: wx.KeyEvent | wx.ListEvent) -> bool:
        key_code = event.GetKeyCode()
        if key_code == wx.WXK_SPACE:
            return self._trigger_preview()
        if key_code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            return self._send_selected_to_music()
        return False

    def _handle_item_activated(self, event: wx.ListEvent) -> None:
        if self._send_selected_to_music():
            return
        event.Skip()

    def _trigger_preview(self) -> bool:
        if not self._on_preview_request:
            return False
        index = self._focused_or_first_index()
        if index is None or index >= len(self.model.items):
            return False
        item = self.model.items[index]
        self._notify_focus()
        self._on_preview_request(self.model.id, item.id)
        return True

    def _send_selected_to_music(self) -> bool:
        if not self._on_send_to_music:
            return False
        indices = self.get_selected_indices()
        if not indices:
            index = self._focused_or_first_index()
            if index is not None:
                indices = [index]
        item_ids = [
            self.model.items[index].id
            for index in indices
            if 0 <= index < len(self.model.items)
        ]
        if not item_ids:
            return False
        self._notify_focus()
        self._on_send_to_music(self.model.id, item_ids)
        return True

    def _focused_or_first_index(self) -> int | None:
        index = self.get_focused_index()
        if index == wx.NOT_FOUND:
            selected = self.get_selected_indices()
            if selected:
                index = selected[0]
        if index == wx.NOT_FOUND and self.model.items:
            index = 0
        return int(index) if index != wx.NOT_FOUND else None
