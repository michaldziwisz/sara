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
    if "speech" not in sys.modules:
        speech_mod = types.ModuleType("speech")
        speech_mod.cancelSpeech = lambda: None  # type: ignore[attr-defined]
        speech_mod.speakMessage = lambda *_a, **_k: None  # type: ignore[attr-defined]
        sys.modules["speech"] = speech_mod
    sys.modules.setdefault(
        "logHandler",
        types.SimpleNamespace(log=types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)),
    )
    if "inputCore" not in sys.modules:
        class _DummyRawKeyRegistry:
            def __init__(self):
                self._items = set()

            def register(self, handler):
                self._items.add(handler)

            def unregister(self, handler):
                self._items.discard(handler)

        input_core = types.ModuleType("inputCore")
        input_core.decide_handleRawKey = _DummyRawKeyRegistry()  # type: ignore[attr-defined]
        input_core.manager = types.SimpleNamespace(emulateGesture=lambda _gesture: None)
        sys.modules["inputCore"] = input_core
    if "keyboardHandler" not in sys.modules:
        class _DummyKeyboardGesture:
            def __init__(self, name: str):
                self.name = name

            @staticmethod
            def fromName(name: str):
                return _DummyKeyboardGesture(name)

        keyboard_handler = types.ModuleType("keyboardHandler")
        keyboard_handler.KeyboardInputGesture = _DummyKeyboardGesture  # type: ignore[attr-defined]
        sys.modules["keyboardHandler"] = keyboard_handler
    if "winUser" not in sys.modules:
        win_user = types.ModuleType("winUser")
        win_user.VK_UP = 38  # type: ignore[attr-defined]
        win_user.VK_DOWN = 40  # type: ignore[attr-defined]
        win_user.VK_SPACE = 32  # type: ignore[attr-defined]
        win_user.VK_F1 = 112  # type: ignore[attr-defined]
        win_user.VK_F6 = 117  # type: ignore[attr-defined]
        sys.modules["winUser"] = win_user

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

    if "appModuleHandler" not in sys.modules:
        app_module_handler = types.ModuleType("appModuleHandler")
        app_module_handler.AppModule = DummyAppModule  # type: ignore[attr-defined]
        sys.modules["appModuleHandler"] = app_module_handler
    if "scriptHandler" not in sys.modules:
        def _script_decorator(*_args, **_kwargs):
            def _wrap(func):
                return func

            return _wrap

        script_handler = types.ModuleType("scriptHandler")
        script_handler.script = _script_decorator  # type: ignore[attr-defined]
        sys.modules["scriptHandler"] = script_handler


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
