"""Helpers for customizing accessibility behaviors."""

from __future__ import annotations

import wx


class SilentListAccessible(wx.Accessible):
    """Accessible wrapper that suppresses spoken names for list items."""

    def __init__(self, window: wx.Window) -> None:
        super().__init__()
        self._window = window

    def GetName(self, childId: int) -> tuple[int, str]:  # noqa: N802 - wx API signature
        return wx.ACC_OK, ""

    def GetDescription(self, childId: int) -> tuple[int, str]:  # noqa: N802 - wx API signature
        return wx.ACC_OK, ""

    def GetValue(self, childId: int) -> tuple[int, str]:  # noqa: N802 - wx API signature
        return wx.ACC_OK, ""


__all__ = ["SilentListAccessible"]
