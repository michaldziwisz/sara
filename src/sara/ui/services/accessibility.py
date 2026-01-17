"""Accessibility helpers for wxPython controls (screen readers / NVDA)."""

from __future__ import annotations

import wx

try:

    class _NamedAccessible(wx.Accessible):
        def __init__(self, window: wx.Window, name: str, description: str | None = None) -> None:
            super().__init__()
            self._window = window
            self._name = name
            self._description = description or ""

        def GetName(self, childId: int):  # noqa: N802 - wx API name
            return (wx.ACC_OK, self._name)

        def GetDescription(self, childId: int):  # noqa: N802 - wx API name
            if self._description:
                return (wx.ACC_OK, self._description)
            return (wx.ACC_NOT_SUPPORTED, "")

        def GetRole(self, childId: int):  # noqa: N802 - wx API name
            if isinstance(self._window, wx.TextCtrl):
                return (wx.ACC_OK, wx.ROLE_SYSTEM_TEXT)
            return (wx.ACC_OK, wx.ROLE_SYSTEM_CLIENT)

        def GetState(self, childId: int):  # noqa: N802 - wx API name
            state = 0
            if not self._window.IsEnabled():
                state |= wx.ACC_STATE_SYSTEM_UNAVAILABLE
            if not self._window.IsShownOnScreen():
                state |= wx.ACC_STATE_SYSTEM_INVISIBLE
            if self._window.HasFocus():
                state |= wx.ACC_STATE_SYSTEM_FOCUSED
            if self._window.CanAcceptFocus():
                state |= wx.ACC_STATE_SYSTEM_FOCUSABLE

            if isinstance(self._window, wx.TextCtrl):
                if not self._window.IsEditable():
                    state |= wx.ACC_STATE_SYSTEM_READONLY
                if self._window.GetWindowStyleFlag() & wx.TE_PASSWORD:
                    state |= wx.ACC_STATE_SYSTEM_PROTECTED

            return (wx.ACC_OK, state)

        def GetValue(self, childId: int):  # noqa: N802 - wx API name
            if isinstance(self._window, wx.TextCtrl):
                if self._window.GetWindowStyleFlag() & wx.TE_PASSWORD:
                    return (wx.ACC_OK, "")
                return (wx.ACC_OK, self._window.GetValue())
            return (wx.ACC_NOT_SUPPORTED, "")

except Exception:  # pragma: no cover - accessibility may be unavailable
    _NamedAccessible = None  # type: ignore[assignment]


def apply_accessible_label(control: wx.Window, label: str, *, description: str | None = None) -> None:
    """Set a screen-reader-friendly name/description on a wx control.

    Note: SARA often used `SetName()` for internal identifiers. For NVDA, we want
    a human-readable label, so this function intentionally sets `SetName()` and
    `SetHelpText()` to user-facing strings.
    """

    try:
        control.SetName(label)
    except Exception:
        pass

    try:
        control.SetHelpText(description or label)
    except Exception:
        pass

    if _NamedAccessible is None:
        return

    if not isinstance(control, wx.TextCtrl):
        return

    try:
        acc = _NamedAccessible(control, label, description or label)
        control.SetAccessible(acc)
        # Keep a strong reference; some platforms can GC the object otherwise.
        setattr(control, "_sara_accessible", acc)
    except Exception:
        pass


__all__ = [
    "apply_accessible_label",
]

