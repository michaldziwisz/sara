"""Application configuration management module."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from sara.core.shortcuts import ensure_defaults

DEFAULT_CONFIG: Dict[str, Any] = {
    "general": {
        "language": "en",
    },
    "shortcuts": {
        "global": {
            "play_next": "SPACE",
            "auto_mix_toggle": "CTRL+SHIFT+M",
            "marker_mode_toggle": "CTRL+SHIFT+ENTER",
            "loop_playback_toggle": "CTRL+SHIFT+L",
            "loop_info": "CTRL+ALT+SHIFT+L",
        },
        "playlist_menu": {
            "new": "CTRL+N",
            "add_tracks": "CTRL+D",
            "assign_device": "CTRL+SHIFT+D",
            "import": "CTRL+O",
            "export": "CTRL+S",
            "exit": "ALT+F4",
        },
        "playlist": {
            "play": "F1",
            "pause": "F2",
            "stop": "F3",
            "fade": "F4",
        },
        "edit": {
            "undo": "CTRL+Z",
            "redo": "CTRL+SHIFT+Z",
            "cut": "CTRL+X",
            "copy": "CTRL+C",
            "paste": "CTRL+V",
            "delete": "DELETE",
            "move_up": "ALT+UP",
            "move_down": "ALT+DOWN",
        },
    },
    "playback": {
        "fade_out_seconds": 0.0,
        "alternate_play_next": False,
        "auto_remove_played": False,
        "focus_playing_track": True,
    },
    "startup": {
        "playlists": [],
    },
    "devices": {
        "playlists": {},
        "pfl": None,
    },
}

ensure_defaults(DEFAULT_CONFIG["shortcuts"])


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)  # type: ignore[arg-type]
        else:
            result[key] = value
    return result


@dataclass
class SettingsManager:
    """Proste zarządzanie konfiguracją YAML z domyślnymi wartościami."""

    config_path: Path = Path("config/settings.yaml")

    def __post_init__(self) -> None:
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if self.config_path.exists():
            with self.config_path.open("r", encoding="utf-8") as file:
                user_config = yaml.safe_load(file) or {}
            if not isinstance(user_config, dict):
                user_config = {}
            self._data = _deep_merge(DEFAULT_CONFIG, user_config)
        else:
            self._data = copy.deepcopy(DEFAULT_CONFIG)

    def save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as file:
            yaml.safe_dump(self._data, file, allow_unicode=False, sort_keys=True)

    def get_global_shortcut(self, action: str) -> str:
        return self.get_shortcut("global", action)

    def get_playlist_shortcuts(self) -> Dict[str, str]:
        return self.get_scope_shortcuts("playlist")

    def get_scope_shortcuts(self, scope: str) -> Dict[str, str]:
        defaults = DEFAULT_CONFIG["shortcuts"].get(scope, {}).copy()
        user_values = (
            self._data
            .get("shortcuts", {})
            .get(scope, {})
        )
        normalized = {key: str(value).upper() for key, value in user_values.items() if isinstance(value, (str, int))}
        defaults.update(normalized)
        return defaults

    def get_shortcut(self, scope: str, action: str) -> str:
        return self.get_scope_shortcuts(scope).get(action, "")

    def get_all_shortcuts(self) -> Dict[str, Dict[str, str]]:
        result: Dict[str, Dict[str, str]] = {}
        scopes = set(DEFAULT_CONFIG["shortcuts"].keys()) | set(self._data.get("shortcuts", {}).keys())
        for scope in scopes:
            result[scope] = self.get_scope_shortcuts(scope)
        return result

    def set_shortcut(self, scope: str, action: str, value: str) -> None:
        parts = [part.strip().upper() for part in str(value).split("+") if part.strip()]
        normalized = "+".join(parts)
        scope_dict = self._data.setdefault("shortcuts", {}).setdefault(scope, {})
        scope_dict[action] = normalized

    def get_raw(self) -> Dict[str, Any]:
        return copy.deepcopy(self._data)

    def get_playback_fade_seconds(self) -> float:
        playback = self._data.get("playback", {})
        value = playback.get("fade_out_seconds", DEFAULT_CONFIG["playback"]["fade_out_seconds"])
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return DEFAULT_CONFIG["playback"]["fade_out_seconds"]

    def set_playback_fade_seconds(self, value: float) -> None:
        playback = self._data.setdefault("playback", {})
        playback["fade_out_seconds"] = max(0.0, float(value))

    def get_alternate_play_next(self) -> bool:
        playback = self._data.get("playback", {})
        return bool(playback.get("alternate_play_next", DEFAULT_CONFIG["playback"]["alternate_play_next"]))

    def set_alternate_play_next(self, enabled: bool) -> None:
        playback = self._data.setdefault("playback", {})
        playback["alternate_play_next"] = bool(enabled)

    def get_auto_remove_played(self) -> bool:
        playback = self._data.get("playback", {})
        return bool(playback.get("auto_remove_played", DEFAULT_CONFIG["playback"]["auto_remove_played"]))

    def set_auto_remove_played(self, enabled: bool) -> None:
        playback = self._data.setdefault("playback", {})
        playback["auto_remove_played"] = bool(enabled)

    def get_focus_playing_track(self) -> bool:
        playback = self._data.get("playback", {})
        return bool(playback.get("focus_playing_track", DEFAULT_CONFIG["playback"]["focus_playing_track"]))

    def set_focus_playing_track(self, enabled: bool) -> None:
        playback = self._data.setdefault("playback", {})
        playback["focus_playing_track"] = bool(enabled)

    def get_language(self) -> str:
        general = self._data.get("general", {})
        return str(general.get("language", DEFAULT_CONFIG["general"]["language"]))

    def set_language(self, language: str) -> None:
        general = self._data.setdefault("general", {})
        general["language"] = language

    def get_startup_playlists(self) -> list[dict[str, Any]]:
        startup = self._data.get("startup", {})
        playlists = startup.get("playlists", [])
        result: list[dict[str, Any]] = []
        if isinstance(playlists, list):
            for entry in playlists:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("name", ""))
                if not name:
                    continue
                slots = entry.get("slots", [])
                normalized_slots: list[Optional[str]] = []
                if isinstance(slots, list):
                    for slot in slots:
                        if slot is None:
                            normalized_slots.append(None)
                        else:
                            normalized_slots.append(str(slot))
                result.append({"name": name, "slots": normalized_slots})
        return result

    def set_startup_playlists(self, playlists: list[dict[str, Any]]) -> None:
        normalized: list[dict[str, Any]] = []
        for entry in playlists:
            name = entry.get("name")
            if not name:
                continue
            slots_raw = entry.get("slots", [])
            slots: list[Optional[str]] = []
            if isinstance(slots_raw, list):
                for slot in slots_raw:
                    if slot is None:
                        slots.append(None)
                    else:
                        slots.append(str(slot))
            normalized.append({"name": str(name), "slots": slots})
        self._data.setdefault("startup", {})["playlists"] = normalized

    def get_playlist_outputs(self, playlist_name: str) -> list[Optional[str]]:
        playlists = (
            self._data
            .get("devices", {})
            .get("playlists", {})
        )
        value = playlists.get(playlist_name)
        if isinstance(value, list):
            outputs: list[Optional[str]] = []
            for entry in value:
                if entry is None:
                    outputs.append(None)
                else:
                    outputs.append(str(entry))
            return outputs
        if isinstance(value, str):  # kompatybilność
            return [value]
        return []

    def set_playlist_outputs(self, playlist_name: str, device_ids: list[Optional[str]]) -> None:
        playlists = self._data.setdefault("devices", {}).setdefault("playlists", {})
        cleaned = [device_id if device_id else None for device_id in device_ids]
        if any(device_id is not None for device_id in cleaned):
            playlists[playlist_name] = cleaned
        else:
            playlists.pop(playlist_name, None)

    # Backward compatibility
    def get_playlist_devices(self, playlist_name: str) -> list[Optional[str]]:  # pragma: no cover - alias
        return self.get_playlist_outputs(playlist_name)

    def set_playlist_devices(self, playlist_name: str, device_ids: list[Optional[str]]) -> None:  # pragma: no cover - alias
        self.set_playlist_outputs(playlist_name, device_ids)

    def get_pfl_device(self) -> Optional[str]:
        devices = self._data.get("devices", {})
        value = devices.get("pfl")
        if value in (None, "", False):
            return None
        return str(value)

    def set_pfl_device(self, device_id: Optional[str]) -> None:
        devices = self._data.setdefault("devices", {})
        devices["pfl"] = str(device_id) if device_id else None
