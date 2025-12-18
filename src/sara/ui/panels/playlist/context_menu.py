"""Context menu handling for the playlist panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

import wx

from sara.core.i18n import gettext as _

if TYPE_CHECKING:
    from sara.ui.panels.playlist.panel import PlaylistPanel


def show_context_menu(panel: "PlaylistPanel", event: wx.ContextMenuEvent) -> None:
    item_index = panel._list_ctrl.GetFocusedItem()
    if item_index == wx.NOT_FOUND and panel._list_ctrl.GetItemCount() > 0:
        item_index = 0
    if item_index == wx.NOT_FOUND:
        event.Skip()
        return

    item = panel.model.items[item_index]
    menu = wx.Menu()

    if panel._on_mix_configure:
        mix_id = wx.NewIdRef()
        menu.Append(mix_id, _("&Mix points…"))

        def _trigger_mix(_evt: wx.CommandEvent) -> None:
            panel._notify_focus()
            panel._on_mix_configure(panel.model.id, item.id)

        panel.Bind(wx.EVT_MENU, _trigger_mix, id=int(mix_id))

    if panel._on_toggle_selection:
        toggle_id = wx.NewIdRef()
        toggle_label = _("&Select for playback") if not item.is_selected else _("Remove &selection")
        menu.Append(toggle_id, toggle_label)

        def _trigger_selection(_evt: wx.CommandEvent) -> None:
            panel._notify_focus()
            panel.set_selection([item_index], focus=True)
            panel._list_ctrl.Focus(item_index)
            panel._on_toggle_selection(panel.model.id, item.id)

        panel.Bind(wx.EVT_MENU, _trigger_selection, id=int(toggle_id))

    if not menu.GetMenuItemCount():
        event.Skip()
        menu.Destroy()
        return

    try:
        panel.PopupMenu(menu)
    finally:
        menu.Destroy()

