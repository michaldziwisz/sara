"""Helpers for handling wxPython keyboard shortcuts."""

from __future__ import annotations

from typing import Optional, Tuple

import wx

MODIFIERS = {
    "CTRL": wx.ACCEL_CTRL,
    "ALT": wx.ACCEL_ALT,
    "SHIFT": wx.ACCEL_SHIFT,
}

KEY_MAP = {
    "SPACE": wx.WXK_SPACE,
    "ENTER": wx.WXK_RETURN,
    "TAB": wx.WXK_TAB,
    "ESC": wx.WXK_ESCAPE,
    "ESCAPE": wx.WXK_ESCAPE,
    "DELETE": wx.WXK_DELETE,
    "BACKSPACE": wx.WXK_BACK,
    "UP": wx.WXK_UP,
    "DOWN": wx.WXK_DOWN,
    "LEFT": wx.WXK_LEFT,
    "RIGHT": wx.WXK_RIGHT,
    "NUMPAD_ENTER": wx.WXK_NUMPAD_ENTER,
}

for num in range(1, 13):
    KEY_MAP[f"F{num}"] = getattr(wx, f"WXK_F{num}")

REVERSE_KEY_MAP = {value: key for key, value in KEY_MAP.items()}

DISPLAY_MODIFIERS = {
    "CTRL": "Ctrl",
    "ALT": "Alt",
    "SHIFT": "Shift",
}

DISPLAY_KEYS = {
    "SPACE": "Spacja",
    "ENTER": "Enter",
    "TAB": "Tab",
    "ESC": "Esc",
    "ESCAPE": "Esc",
    "DELETE": "Delete",
    "BACKSPACE": "Backspace",
    "UP": "Up arrow",
    "DOWN": "Down arrow",
    "LEFT": "Left arrow",
    "RIGHT": "Right arrow",
    "NUMPAD_ENTER": "Enter num.",
}

ALIASES = {
    "DEL": "DELETE",
    "RETURN": "ENTER",
    "NUMPADENTER": "NUMPAD_ENTER",
}


def normalize_shortcut(shortcut: str) -> str:
    """Normalise shortcut string representation (modifier order, aliases, casing)."""

    if not shortcut:
        return ""

    raw_parts = [part.strip().upper() for part in str(shortcut).split("+") if part.strip()]
    if not raw_parts:
        return ""

    modifiers: list[str] = []
    key_part: str | None = None

    for part in raw_parts:
        canonical = ALIASES.get(part, part)
        if canonical in MODIFIERS:
            if canonical not in modifiers:
                modifiers.append(canonical)
        else:
            key_part = canonical if len(canonical) != 1 else canonical.upper()

    if key_part is None:
        return ""

    ordered_modifiers = [name for name in ("CTRL", "ALT", "SHIFT") if name in modifiers]
    return "+".join(ordered_modifiers + [key_part])


def parse_shortcut(shortcut: str) -> Optional[Tuple[int, int]]:
    """Convert a textual representation like "CTRL+ALT+K" into (modifiers, keycode)."""

    if not shortcut:
        return None

    parts = [part.strip().upper() for part in shortcut.split("+") if part.strip()]
    if not parts:
        return None

    modifiers = 0
    key_part = None

    for part in parts:
        if part in MODIFIERS:
            modifiers |= MODIFIERS[part]
        else:
            key_part = ALIASES.get(part, part)

    if key_part is None:
        return None

    if key_part in KEY_MAP:
        keycode = KEY_MAP[key_part]
    elif len(key_part) == 1:
        keycode = ord(key_part)
    else:
        return None

    return modifiers, keycode


def format_shortcut_display(shortcut: str) -> str:
    normalized = normalize_shortcut(shortcut)
    if not normalized:
        return ""
    display_parts = []
    for part in normalized.split("+"):
        alias_part = ALIASES.get(part, part)
        if alias_part in DISPLAY_MODIFIERS:
            display_parts.append(DISPLAY_MODIFIERS[alias_part])
        elif alias_part in DISPLAY_KEYS:
            display_parts.append(DISPLAY_KEYS[alias_part])
        elif len(part) == 1:
            display_parts.append(part.upper())
        else:
            display_parts.append(alias_part.title())
    return "+".join(display_parts)


def accelerator_to_string(modifiers: int, keycode: int) -> str:
    parts = []
    for name, flag in MODIFIERS.items():
        if modifiers & flag:
            parts.append(name)

    if keycode in REVERSE_KEY_MAP:
        parts.append(REVERSE_KEY_MAP[keycode])
    elif 32 <= keycode <= 126:
        parts.append(chr(keycode).upper())
    else:
        return ""

    return normalize_shortcut("+".join(parts))


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

