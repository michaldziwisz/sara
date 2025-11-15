"""Lightweight settings for the standalone news editor."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

import yaml


def _application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _default_config_path() -> Path:
    env_override = os.environ.get("SARA_NEWS_EDITOR_CONFIG")
    if env_override:
        return Path(env_override).expanduser()
    return _application_root() / "config" / "news_editor.yaml"


class NewsEditorSettings:
    """Persist editor-specific preferences near the application folder."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = Path(config_path) if config_path else _default_config_path()
        self._data: Dict[str, Any] = {}
        self.load()

    def _load_from_path(self, path: Path) -> Dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as stream:
                raw = yaml.safe_load(stream) or {}
        except Exception:
            return {}
        return raw if isinstance(raw, dict) else {}

    def load(self) -> None:
        if self.config_path.exists():
            self._data = self._load_from_path(self.config_path)
            return
        self._data = {}

    def save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as stream:
            yaml.safe_dump(self._data, stream, allow_unicode=True, sort_keys=True)

    # ------------------------------------------------------------------ options
    def get_last_device_id(self) -> str | None:
        value = self._data.get("last_device_id")
        return str(value) if isinstance(value, str) and value else None

    def set_last_device_id(self, device_id: str | None) -> None:
        if device_id:
            self._data["last_device_id"] = device_id
        else:
            self._data.pop("last_device_id", None)
        self.save()

    def get_line_length(self, default: int) -> int:
        value = self._data.get("line_length")
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return default

    def set_line_length(self, value: int) -> None:
        self._data["line_length"] = max(0, int(value))
        self.save()
