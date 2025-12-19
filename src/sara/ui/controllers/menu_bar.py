"""Compatibility wrapper for menu bar helpers.

Implementation lives in `sara.ui.controllers.menu.menu_bar`.
"""

from __future__ import annotations

from sara.ui.controllers.menu.menu_bar import (
    append_shortcut_menu_item,
    apply_shortcut_to_menu_item,
    create_menu_bar,
    register_menu_shortcut,
    update_shortcut_menu_labels,
)

__all__ = [
    "append_shortcut_menu_item",
    "apply_shortcut_to_menu_item",
    "create_menu_bar",
    "register_menu_shortcut",
    "update_shortcut_menu_labels",
]

