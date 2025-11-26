"""Smoke test for the wxPython GUI using pywinauto on Windows."""

from __future__ import annotations

import os
import sys
import time
import re
from pathlib import Path

import pytest
import yaml

pywinauto = pytest.importorskip("pywinauto")
from pywinauto.application import Application  # type: ignore  # noqa: E402
from pywinauto.findwindows import ElementNotFoundError  # type: ignore  # noqa: E402
from pywinauto import Desktop  # type: ignore  # noqa: E402
from pywinauto.keyboard import send_keys  # type: ignore  # noqa: E402


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows-only UI automation"),
    pytest.mark.skipif(
        not os.environ.get("RUN_SARA_E2E"),
        reason="Set RUN_SARA_E2E=1 to run UI automation",
    ),
]


def _find_control(window, identifier: str):
    """Try common lookup strategies for controls with SetName-assigned identifiers."""

    strategies = [
        {"auto_id": identifier},
        {"best_match": identifier},
        {"title": identifier},
    ]
    for query in strategies:
        spec = window.child_window(**query)
        try:
            if spec.exists(timeout=0.5):
                return spec
        except ElementNotFoundError:
            continue
    return None


def _set_text_value(control, value: str) -> None:
    wrapper = control.wrapper_object()
    if hasattr(wrapper, "set_value"):
        wrapper.set_value(value)
    elif hasattr(wrapper, "set_edit_text"):
        wrapper.set_edit_text(value)
    else:
        wrapper.type_keys("^a" + value)


def _click_button(window, *, identifier: str, fallback_title: str) -> None:
    control = _find_control(window, identifier)
    if control is None:
        buttons = window.descendants(control_type="Button", title_re=fallback_title)
        if buttons:
            control = buttons[0]
    if control is None:
        raise AssertionError(f"Button {identifier} not found")
    control.wait("enabled", timeout=5)
    control.click_input()


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
        # run from repo root so resources are available
        work_dir = str(Path(__file__).resolve().parents[2])
        app = Application(backend="uia")
        app.start(
            cmd,
            work_dir=work_dir,
            timeout=90,
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


def _wait_for_main(app: Application, title_re: str = "SARA", timeout: float = 60.0):
    desktop = Desktop(backend="uia")
    desktop_win32 = Desktop(backend="win32")
    deadline = time.time() + timeout
    while time.time() < deadline:
        for coll, backend in ((desktop.windows(), desktop), (desktop_win32.windows(), desktop)):
            for w in coll:
                try:
                    if re.search(title_re, w.window_text(), re.IGNORECASE):
                        return backend.window(handle=w.handle)
                except Exception:
                    continue
        time.sleep(1.0)
    print("Last windows (uia):", [(w.window_text(), getattr(w, "process_id", lambda: None)()) for w in desktop.windows()])
    print("Last windows (win32):", [(w.window_text(), getattr(w, "process_id", lambda: None)()) for w in desktop_win32.windows()])
    raise RuntimeError("Main window not found")


def _wait_for_child_dialog(app: Application, exclude_handle: int, timeout: float = 10.0):
    desktop = Desktop(backend="uia")
    deadline = time.time() + timeout
    while time.time() < deadline:
        for win in desktop.windows():
            try:
                if win.process_id() == app.process and win.handle != exclude_handle:
                    return win
            except Exception:
                continue
        time.sleep(0.5)
    return None


def _menu_select_with_fallbacks(window, paths, key_sequences=None, names=None):
    errors = []
    for path in paths:
        try:
            window.menu_select(path)
            return
        except Exception as exc:  # noqa: BLE001
            errors.append((path, exc))
    for seq in key_sequences or []:
        try:
            send_keys(seq, pause=0.1)
            time.sleep(0.5)
            return
        except Exception as exc:  # noqa: BLE001
            errors.append((f"keys:{seq}", exc))
    for name in names or []:
        try:
            items = window.descendants(control_type="MenuItem")
            for item in items:
                try:
                    if name.lower() in item.window_text().lower():
                        item.select()
                        return
                except Exception:
                    continue
        except Exception as exc:  # noqa: BLE001
            errors.append((f"menu_items:{name}", exc))
    raise RuntimeError(f"Menu selection failed: {errors}")


def _ensure_playlist(main):
    """Create a playlist via Ctrl+N and accept default dialog."""
    send_keys("^n", pause=0.1)
    time.sleep(0.5)
    desktop = Desktop(backend="uia")
    for win in desktop.windows():
        try:
            title = win.window_text()
            if "playlist" in title.lower() or "lista" in title.lower():
                win.set_focus()
                send_keys("E2E{ENTER}", pause=0.05)
                time.sleep(0.5)
                return
        except Exception:
            continue


def test_options_dialog_roundtrip(tmp_path):
    app = _start_app(tmp_path)
    try:
        main = _wait_for_main(app, title_re="SARA", timeout=90.0)
        try:
            main.wait("exists", timeout=90)
            main.wait("visible", timeout=20)
        except Exception:
            # diagnostic: list windows if main not found
            windows = Desktop(backend="uia").windows()
            print(
                "Open windows (uia):",
                [(w.window_text(), getattr(w, "process_id", lambda: None)()) for w in windows],
            )
            raise
        main.set_focus()
        _ensure_playlist(main)
        _menu_select_with_fallbacks(
            main,
            paths=[
                "Options…",
                "Options...",
                "Opcje…",
                "Opcje...",
                "Tools->Options…",
                "Tools->Options...",
                "Narzędzia->Opcje…",
                "Narzędzia->Opcje...",
            ],
            key_sequences=["%to", "%t o", "%no", "%n o"],  # Alt+T then O (English/Polish UI)
            names=["Options", "Opcje"],
        )

        dialog = app.window(title_re="Options|Opcje")
        dialog = _wait_for_child_dialog(app, exclude_handle=main.handle, timeout=10) or dialog
        dialog.wait("exists", timeout=5)
        dialog.wait("visible", timeout=5)
        # minimal smoke: just ensure dialog appears, then close
        try:
            send_keys("{ESC}")
        except Exception:
            pass
    finally:
        app.kill()
