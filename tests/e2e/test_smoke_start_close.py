"""Minimal smoke test: start SARA, detect main window, then close."""

from __future__ import annotations

import os
import sys
import time
import re
from pathlib import Path

import pytest

pywinauto = pytest.importorskip("pywinauto")
from pywinauto.application import Application  # type: ignore  # noqa: E402
from pywinauto import Desktop  # type: ignore  # noqa: E402


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows-only UI automation"),
    pytest.mark.skipif(
        not os.environ.get("RUN_SARA_E2E"),
        reason="Set RUN_SARA_E2E=1 to run UI automation",
    ),
]


def _start_app(tmp_path: Path) -> Application:
    env_overrides = {
        "SARA_E2E": "1",
        "SARA_CONFIG_DIR": str(tmp_path / "config"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
    }
    original: dict[str, str | None] = {}
    for key, value in env_overrides.items():
        original[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        cmd = f'"{sys.executable}" -m sara.app'
        work_dir = str(Path(__file__).resolve().parents[2])
        app = Application(backend="uia")
        app.start(
            cmd,
            work_dir=work_dir,
            timeout=20,  # keep short to fail fast in CI/local runs
            wait_for_idle=False,
            create_new_console=True,
        )
        return app
    finally:
        for key, prev in original.items():
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev


def _wait_for_main(app: Application, title_re: str = "SARA", timeout: float = 20.0):
    desktop = Desktop(backend="uia")
    desktop_win32 = Desktop(backend="win32")
    deadline = time.time() + timeout
    while time.time() < deadline:
        for coll, backend in ((desktop.windows(), desktop), (desktop_win32.windows(), desktop)):
            for w in coll:
                try:
                    if not re.search(title_re, w.window_text(), re.IGNORECASE):
                        continue
                    # prefer matching window, even if pid differs (e.g. existing instance)
                    return backend.window(handle=w.handle)
                except Exception:
                    continue
        time.sleep(1.0)
    print("Windows UIA:", [(w.window_text(), getattr(w, "process_id", lambda: None)()) for w in desktop.windows()])
    print("Windows win32:", [(w.window_text(), getattr(w, "process_id", lambda: None)()) for w in desktop_win32.windows()])
    raise RuntimeError("Main window not found during smoke start")


def test_smoke_start_and_close(tmp_path):
    app = _start_app(tmp_path)
    try:
        main = _wait_for_main(app, timeout=20.0)
        assert main is not None
        # close gracefully
        main.type_keys("%{F4}")  # Alt+F4
        # give it a moment, then kill if still alive
        time.sleep(2.0)
    finally:
        try:
            app.kill()
        except Exception:
            pass
