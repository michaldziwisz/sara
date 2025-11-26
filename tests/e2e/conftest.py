from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end UI tests (Windows only)")


@pytest.fixture(scope="session")
def sara_env(tmp_path_factory):
    """Common environment for SARA E2E runs."""

    workdir = tmp_path_factory.mktemp("sara_e2e_run")
    env = os.environ.copy()
    env.setdefault("SARA_E2E", "1")
    env["SARA_CONFIG_DIR"] = str(workdir / "config")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    return workdir, env
