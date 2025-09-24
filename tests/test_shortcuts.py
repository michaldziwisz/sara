"""Tests covering shortcut utilities and shortcut configuration defaults."""

from __future__ import annotations

import pytest

try:
    import wx
except ImportError:  # pragma: no cover - wx not available in some CI environments
    wx = None  # type: ignore[assignment]
    pytest.skip("wxPython is required for shortcut utility tests", allow_module_level=True)

from sara.core.config import SettingsManager
from sara.ui.shortcut_utils import (
    accelerator_to_string,
    format_shortcut_display,
    normalize_shortcut,
    parse_shortcut,
)


def test_normalize_shortcut_orders_modifiers_and_aliases() -> None:
    assert normalize_shortcut(" alt + ctrl + shift + o ") == "CTRL+ALT+SHIFT+O"
    assert normalize_shortcut("ctrl+del") == "CTRL+DELETE"
    assert normalize_shortcut("ctrl + ctrl + return") == "CTRL+ENTER"
    assert normalize_shortcut("ctrl+numpadenter") == "CTRL+NUMPAD_ENTER"


def test_accelerator_round_trip_for_ctrl_enter_variants() -> None:
    modifiers, keycode = parse_shortcut("CTRL+ENTER")
    assert modifiers == wx.ACCEL_CTRL
    assert keycode == wx.WXK_RETURN

    as_text = accelerator_to_string(modifiers, keycode)
    assert as_text == "CTRL+ENTER"

    numpad_text = accelerator_to_string(wx.ACCEL_CTRL, wx.WXK_NUMPAD_ENTER)
    assert numpad_text == "CTRL+NUMPAD_ENTER"
    assert format_shortcut_display(numpad_text) == "Ctrl+Enter num."


def test_settings_manager_exposes_playlist_menu_shortcuts(tmp_path) -> None:
    manager = SettingsManager(config_path=tmp_path / "settings.yaml")

    shortcuts = manager.get_all_shortcuts()
    assert shortcuts["playlist_menu"]["new"] == "CTRL+N"
    assert shortcuts["playlist_menu"]["exit"] == "ALT+F4"

    manager.set_shortcut("playlist_menu", "new", " alt + shift + p ")
    assert manager.get_shortcut("playlist_menu", "new") == "ALT+SHIFT+P"
