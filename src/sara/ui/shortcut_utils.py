"""Compatibility wrapper for shortcut utilities.

Implementation lives in `sara.ui.shortcuts.utils`.
"""

from __future__ import annotations

from sara.ui.shortcuts.utils import (
    ALIASES,
    DISPLAY_KEYS,
    DISPLAY_MODIFIERS,
    KEY_MAP,
    MODIFIERS,
    REVERSE_KEY_MAP,
    accelerator_to_string,
    format_shortcut_display,
    normalize_shortcut,
    parse_shortcut,
)

__all__ = [
    "ALIASES",
    "DISPLAY_KEYS",
    "DISPLAY_MODIFIERS",
    "KEY_MAP",
    "MODIFIERS",
    "REVERSE_KEY_MAP",
    "accelerator_to_string",
    "format_shortcut_display",
    "normalize_shortcut",
    "parse_shortcut",
]
