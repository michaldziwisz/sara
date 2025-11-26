"""Helpers for environment flags shared across the app."""

from __future__ import annotations

import os
from pathlib import Path


def is_e2e_mode() -> bool:
    """Return True when end-to-end (UI) tests should run with mock dependencies."""

    flag = os.environ.get("SARA_E2E", "")
    return str(flag).strip().lower() in {"1", "true", "yes", "on"}


def resolve_config_path(default_path: Path) -> Path:
    """Pick config path based on environment overrides."""

    env_path = os.environ.get("SARA_CONFIG_PATH")
    if env_path:
        return Path(env_path)
    env_dir = os.environ.get("SARA_CONFIG_DIR")
    if env_dir:
        return Path(env_dir) / "settings.yaml"
    return default_path
