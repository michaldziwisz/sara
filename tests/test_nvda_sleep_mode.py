from __future__ import annotations

import json
import os

import pytest

from sara.ui.nvda_sleep import ensure_nvda_sleep_mode, notify_nvda_play_next


def test_ensure_nvda_sleep_mode_is_noop_in_e2e(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SARA_E2E", "1")
    monkeypatch.setenv("APPDATA", str(tmp_path))

    ensure_nvda_sleep_mode()

    assert not (tmp_path / "NVDA").exists()
    assert not (tmp_path / "SARA").exists()


def test_ensure_nvda_sleep_mode_writes_app_module_and_registry(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("SARA_E2E", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    ensure_nvda_sleep_mode()

    # NVDA app module files
    app_modules = tmp_path / "NVDA" / "appModules"
    assert (app_modules / "__init__.py").exists()
    assert (app_modules / "python.py").exists()
    assert (app_modules / "sara.py").exists()
    assert (app_modules / "SARA.py").exists()

    # Sleep registry (contains the current pid)
    registry_path = tmp_path / "SARA" / "nvda_sleep_targets.json"
    assert registry_path.exists()
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    assert os.getpid() in set(data.get("pids", []))


def test_notify_nvda_play_next_writes_signal_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))

    notify_nvda_play_next()

    signal_path = tmp_path / "SARA" / "nvda_play_next_signal.txt"
    assert signal_path.exists()
    # content is a timestamp string
    float(signal_path.read_text(encoding="utf-8"))

