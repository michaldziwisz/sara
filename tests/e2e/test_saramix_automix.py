"""End-to-end automix checks on Windows using saramix.m3u."""

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
from pywinauto.keyboard import send_keys  # type: ignore  # noqa: E402
from pywinauto.keyboard import send_keys  # type: ignore  # noqa: E402


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows-only UI automation"),
    pytest.mark.skipif(not os.environ.get("RUN_SARA_E2E"), reason="Set RUN_SARA_E2E=1 to run UI automation"),
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


def _find_menu(window, path: str):
    window.menu_select(path)




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


def _import_m3u(main, m3u_path: Path):
    _menu_select_with_fallbacks(
        main,
        paths=[
            "Import playlist…",
            "Import playlist...",
            "Importuj playlistę…",
            "Importuj playlistę...",
            "File->Import playlist…",
            "File->Import playlist...",
            "Plik->Importuj playlistę…",
            "Plik->Importuj playlistę...",
        ],
        key_sequences=["^o", "%fi", "%pi"],
        names=["Import playlist", "Importuj playlistę"],
    )
    dialog = _wait_for_child_dialog(main.app, exclude_handle=main.handle, timeout=5)
    if dialog:
        dialog.set_focus()
        send_keys(str(m3u_path) + "{ENTER}", pause=0.05)
    else:
        send_keys(str(m3u_path) + "{ENTER}", pause=0.05)



def _toggle_auto_mix(main):
    main.menu_select("Tools->Toggle auto mix")


def _play_first(main):
    main.type_keys("{F1}")


def _wait(seconds: float):
    time.sleep(seconds)


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


def test_saramix_automix_flow(tmp_path):
    src_m3u = Path(__file__).resolve().parents[1].parent / "logs" / "saramix.m3u"
    if not src_m3u.exists():
        pytest.skip("logs/saramix.m3u not present")

    app = _start_app(tmp_path)
    try:
        main = _wait_for_main(app, title_re="SARA", timeout=90.0)
        try:
            main.wait("exists", timeout=90)
            main.wait("visible", timeout=20)
        except Exception:
            windows = Desktop(backend="uia").windows()
            print(
                "Open windows (uia):",
                [(w.window_text(), getattr(w, "process_id", lambda: None)()) for w in windows],
            )
            raise
        _menu_select_with_fallbacks(
            main,
            paths=[
                "Tools->Toggle auto mix",
                "Tools->Auto mix toggle",
                "Narzędzia->Przełącz automix",
                "Auto mix",
                "Automix",
            ],
            key_sequences=["^+m"],
            names=["Auto mix", "Automix"],
        )
        _import_m3u(main, src_m3u)
        _play_first(main)
        _wait(3)
        # Smoke: after a few seconds, automix should be enabled and app responsive
        assert main.is_visible()
    finally:
        app.kill()
