"""Regression tests for playlist panel shortcut dispatch."""

from __future__ import annotations

import pytest

try:
    import wx
except ImportError:  # pragma: no cover - wx not available in some CI environments
    wx = None  # type: ignore[assignment]
    pytest.skip("wxPython is required for playlist shortcut tests", allow_module_level=True)

from sara.ui.panels.playlist import shortcuts as playlist_shortcuts


class _DummyKeyEvent:
    def __init__(self) -> None:
        self.skip_calls: list[bool] = []

    def Skip(self, allow: bool = True) -> None:  # noqa: N802 - wxPython API naming
        self.skip_calls.append(bool(allow))


class _DummyListEvent(_DummyKeyEvent):
    def __init__(self, key_code: int) -> None:
        super().__init__()
        self._key_code = int(key_code)

    def GetKeyCode(self) -> int:  # noqa: N802 - wxPython API naming
        return self._key_code


class _FakePanel:
    def __init__(self, *, selection_handled: bool, navigation_handled: bool = False) -> None:
        self.selection_handled = selection_handled
        self.navigation_handled = navigation_handled
        self.calls: list[str] = []

    def _handle_navigation_key(self, _event) -> bool:
        self.calls.append("nav")
        return self.navigation_handled

    def _handle_selection_key_event(self, _event) -> bool:
        self.calls.append("selection")
        return self.selection_handled

    def _move_focus_by_delta(self, _delta: int) -> bool:
        self.calls.append("move_focus")
        return True


@pytest.mark.parametrize("handler_name", ["handle_key_down", "handle_char_hook", "handle_char"])
def test_key_handlers_delegate_to_panel_methods(monkeypatch: pytest.MonkeyPatch, handler_name: str) -> None:
    monkeypatch.setattr(
        playlist_shortcuts,
        "handle_navigation_key",
        lambda *_args, **_kwargs: pytest.fail("Unexpected module-level navigation handler call"),
    )
    monkeypatch.setattr(
        playlist_shortcuts,
        "handle_selection_key_event",
        lambda *_args, **_kwargs: pytest.fail("Unexpected module-level selection handler call"),
    )

    panel = _FakePanel(selection_handled=True, navigation_handled=False)
    event = _DummyKeyEvent()

    handler = getattr(playlist_shortcuts, handler_name)
    handler(panel, event)

    assert panel.calls == ["nav", "selection"]
    assert event.skip_calls == []


def test_list_key_down_delegates_to_panel_selection_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        playlist_shortcuts,
        "handle_selection_key_event",
        lambda *_args, **_kwargs: pytest.fail("Unexpected module-level selection handler call"),
    )

    panel = _FakePanel(selection_handled=True)
    event = _DummyListEvent(wx.WXK_SPACE)

    playlist_shortcuts.handle_list_key_down(panel, event)

    assert panel.calls == ["selection"]
    assert event.skip_calls == []

