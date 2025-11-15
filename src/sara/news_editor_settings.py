"""Lightweight settings for the standalone news editor."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


class NewsEditorSettings:
    """Persist editor-specific preferences without touching the main SARA config."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or Path("config/news_editor.yaml")
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if self.config_path.exists():
            try:
                with self.config_path.open("r", encoding="utf-8") as stream:
                    raw = yaml.safe_load(stream) or {}
            except Exception:
                raw = {}
        else:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        self._data = raw

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
