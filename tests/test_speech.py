import types
from pathlib import Path

from sara.ui import speech


def test_speak_text_returns_false_without_windows(monkeypatch):
    speech._NVDA_CLIENT.reset()
    monkeypatch.setattr(speech, "_is_windows", lambda: False)
    assert speech.speak_text("test message") is False


def test_speak_text_ignores_empty_messages():
    speech._NVDA_CLIENT.reset()
    assert speech.speak_text("") is False


def test_speak_text_loads_dll_from_env(monkeypatch, tmp_path):
    speech._NVDA_CLIENT.reset()
    monkeypatch.setattr(speech, "_is_windows", lambda: True)

    dll_path = tmp_path / "nvdaControllerClient.dll"
    dll_path.write_bytes(b"")
    monkeypatch.setenv("NVDA_CONTROLLER_DLL", str(tmp_path))

    called_with = {}

    class DummyFunction:
        def __call__(self, value):
            called_with["value"] = getattr(value, "value", value)
            return 0

    class DummyDll:
        def __init__(self):
            self.nvdaController_speakText = DummyFunction()

    def fake_c_wchar_p(value: str):
        return types.SimpleNamespace(value=value)

    loaded = {}

    def fake_windll(path: str):
        loaded["path"] = path
        if not Path(path).exists():
            raise OSError("not found")
        return DummyDll()

    fake_ctypes = types.SimpleNamespace(WinDLL=fake_windll, c_wchar_p=fake_c_wchar_p, c_int=int)
    monkeypatch.setattr(speech, "ctypes", fake_ctypes)

    assert speech.speak_text("Halo") is True
    assert called_with["value"] == "Halo"
    assert loaded["path"].endswith("nvdaControllerClient.dll")
