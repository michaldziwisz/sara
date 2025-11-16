import importlib
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _install_stubs(tmp_path):
    sys.modules.setdefault("api", types.SimpleNamespace(getFocusObject=lambda: None))
    sys.modules.setdefault("core", types.SimpleNamespace(callLater=lambda _ms, cb: types.SimpleNamespace(Stop=lambda: None)))
    sys.modules.setdefault("speech", types.SimpleNamespace(cancelSpeech=lambda: None))
    sys.modules.setdefault(
        "logHandler",
        types.SimpleNamespace(log=types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)),
    )

    class DummyRole:
        PANE = "PANE"
        CLIENT = "CLIENT"
        WINDOW = "WINDOW"
        UNKNOWN = "UNKNOWN"
        LIST = "LIST"
        LISTITEM = "LISTITEM"

    sys.modules.setdefault("controlTypes", types.SimpleNamespace(Role=DummyRole, STATE_SELECTED=0))

    class DummyAppModule:
        def __init__(self, *args, **kwargs):
            pass

        def bindGestures(self, _gestures):
            pass

    sys.modules.setdefault("appModuleHandler", types.SimpleNamespace(AppModule=DummyAppModule))


@pytest.fixture()
def sara_addon(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _install_stubs(tmp_path)
    module = importlib.import_module("nvda_addon.sara_silent.appModules.sara_common")
    return module


def test_gesture_variants_cover_desktop_and_generic(sara_addon):
    variants = sara_addon._gesture_variants(("space",))
    assert "kb:space" in variants
    assert "kb(desktop):space" in variants


def test_is_playlist_window_detects_parent_class(sara_addon):
    class Parent:
        windowClassName = "SysListView32"
        role = sys.modules["controlTypes"].Role.LIST
        parent = None

    class Child:
        windowClassName = "child"
        role = None
        parent = Parent()

    assert sara_addon._is_playlist_window(Child())


def test_is_playing_entry_detects_playing_suffix(sara_addon):
    dummy = types.SimpleNamespace(name="Track ; Playing (muza)")
    assert sara_addon._is_playing_entry(dummy) is True
    assert sara_addon._is_playing_entry(types.SimpleNamespace(name="Track")) is False
