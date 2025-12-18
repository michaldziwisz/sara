"""Menu/accelerator wiring extracted from the main frame."""

from __future__ import annotations

from .accelerators import configure_accelerators
from .global_shortcuts import (
    handle_global_char_hook,
    handle_jingles_key,
    should_handle_altgr_track_remaining,
)
from .menu_bar import (
    append_shortcut_menu_item,
    apply_shortcut_to_menu_item,
    create_menu_bar,
    register_menu_shortcut,
    update_shortcut_menu_labels,
)
