"""Application configuration management module."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .defaults import DEFAULT_ANNOUNCEMENTS, DEFAULT_CONFIG
from .merge import _deep_merge
from sara.core.announcement_registry import ANNOUNCEMENT_CATEGORIES
from sara.core.playlist import PlaylistKind
from sara.core.env import resolve_config_path


@dataclass
class SettingsManager:
    """Proste zarządzanie konfiguracją YAML z domyślnymi wartościami."""

    config_path: Path = Path("config/settings.yaml")

    def __post_init__(self) -> None:
        self.config_path = resolve_config_path(self.config_path)
        self._data: Dict[str, Any] = {}
        self._user_config: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if self.config_path.exists():
            with self.config_path.open("r", encoding="utf-8") as file:
                user_config = yaml.safe_load(file) or {}
            if not isinstance(user_config, dict):
                user_config = {}
            self._user_config = copy.deepcopy(user_config)
            self._data = _deep_merge(DEFAULT_CONFIG, user_config)
        else:
            self._user_config = {}
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

    def get_swap_play_select(self) -> bool:
        playback = self._data.get("playback", {})
        return bool(playback.get("swap_play_select", DEFAULT_CONFIG["playback"]["swap_play_select"]))

    def set_swap_play_select(self, enabled: bool) -> None:
        playback = self._data.setdefault("playback", {})
        playback["swap_play_select"] = bool(enabled)

    def get_focus_playing_track(self) -> bool:
        accessibility_raw = self._user_config.get("accessibility", {}) if isinstance(self._user_config, dict) else {}
        if isinstance(accessibility_raw, dict) and "follow_playing_selection" in accessibility_raw:
            return bool(accessibility_raw.get("follow_playing_selection"))

        playback_raw = self._user_config.get("playback", {}) if isinstance(self._user_config, dict) else {}
        if isinstance(playback_raw, dict) and "focus_playing_track" in playback_raw:
            return bool(playback_raw.get("focus_playing_track"))

        accessibility = self._data.get("accessibility", {})
        return bool(accessibility.get("follow_playing_selection", DEFAULT_CONFIG["accessibility"]["follow_playing_selection"]))

    def set_focus_playing_track(self, enabled: bool) -> None:
        accessibility = self._data.setdefault("accessibility", {})
        accessibility["follow_playing_selection"] = bool(enabled)
        # Remove legacy location to keep saved config clean.
        playback = self._data.setdefault("playback", {})
        playback.pop("focus_playing_track", None)
        if isinstance(self._user_config, dict):
            accessibility_raw = self._user_config.setdefault("accessibility", {})
            if isinstance(accessibility_raw, dict):
                accessibility_raw["follow_playing_selection"] = bool(enabled)
            playback_raw = self._user_config.setdefault("playback", {})
            if isinstance(playback_raw, dict):
                playback_raw.pop("focus_playing_track", None)

    # --- diagnostics ---
    def get_diagnostics_faulthandler(self) -> bool:
        diagnostics = self._data.get("diagnostics", {})
        return bool(diagnostics.get("faulthandler", DEFAULT_CONFIG["diagnostics"]["faulthandler"]))

    def set_diagnostics_faulthandler(self, enabled: bool) -> None:
        diagnostics = self._data.setdefault("diagnostics", {})
        diagnostics["faulthandler"] = bool(enabled)

    def get_diagnostics_faulthandler_interval(self) -> float:
        diagnostics = self._data.get("diagnostics", {})
        value = diagnostics.get("faulthandler_interval", DEFAULT_CONFIG["diagnostics"]["faulthandler_interval"])
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return DEFAULT_CONFIG["diagnostics"]["faulthandler_interval"]

    def set_diagnostics_faulthandler_interval(self, value: float) -> None:
        diagnostics = self._data.setdefault("diagnostics", {})
        diagnostics["faulthandler_interval"] = max(0.0, float(value))

    def get_diagnostics_loop_debug(self) -> bool:
        diagnostics = self._data.get("diagnostics", {})
        return bool(diagnostics.get("loop_debug", DEFAULT_CONFIG["diagnostics"]["loop_debug"]))

    def set_diagnostics_loop_debug(self, enabled: bool) -> None:
        diagnostics = self._data.setdefault("diagnostics", {})
        diagnostics["loop_debug"] = bool(enabled)

    def get_diagnostics_log_level(self) -> str:
        diagnostics = self._data.get("diagnostics", {})
        level = str(diagnostics.get("log_level", DEFAULT_CONFIG["diagnostics"]["log_level"])).upper()
        return level if level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") else DEFAULT_CONFIG["diagnostics"]["log_level"]

    def set_diagnostics_log_level(self, level: str) -> None:
        diagnostics = self._data.setdefault("diagnostics", {})
        diagnostics["log_level"] = str(level).upper()

    def get_intro_alert_seconds(self) -> float:
        playback = self._data.get("playback", {})
        value = playback.get("intro_alert_seconds", DEFAULT_CONFIG["playback"]["intro_alert_seconds"])
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return DEFAULT_CONFIG["playback"]["intro_alert_seconds"]

    def set_intro_alert_seconds(self, seconds: float) -> None:
        playback = self._data.setdefault("playback", {})
        playback["intro_alert_seconds"] = max(0.0, float(seconds))

    def get_track_end_alert_seconds(self) -> float:
        playback = self._data.get("playback", {})
        value = playback.get("track_end_alert_seconds", DEFAULT_CONFIG["playback"]["track_end_alert_seconds"])
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return DEFAULT_CONFIG["playback"]["track_end_alert_seconds"]

    def set_track_end_alert_seconds(self, seconds: float) -> None:
        playback = self._data.setdefault("playback", {})
        playback["track_end_alert_seconds"] = max(0.0, float(seconds))

    def get_news_line_length(self) -> int:
        news = self._data.get("news", {})
        value = news.get("line_length", DEFAULT_CONFIG["news"]["line_length"])
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return DEFAULT_CONFIG["news"]["line_length"]

    def set_news_line_length(self, line_length: int) -> None:
        news = self._data.setdefault("news", {})
        news["line_length"] = max(0, int(line_length))

    def _announcement_settings(self) -> dict[str, bool]:
        accessibility = self._data.setdefault("accessibility", {})
        announcements = accessibility.setdefault("announcements", {})
        return announcements  # type: ignore[return-value]

    def get_announcement_enabled(self, category: str) -> bool:
        announcements = self._announcement_settings()
        if category in announcements:
            return bool(announcements[category])
        return DEFAULT_ANNOUNCEMENTS.get(category, True)

    def set_announcement_enabled(self, category: str, enabled: bool) -> None:
        announcements = self._announcement_settings()
        announcements[category] = bool(enabled)

    def get_all_announcement_settings(self) -> dict[str, bool]:
        return {
            category.id: self.get_announcement_enabled(category.id)
            for category in ANNOUNCEMENT_CATEGORIES
        }

    # --- playback logging ---
    def get_played_tracks_logging_enabled(self) -> bool:
        logging_cfg = self._data.get("logging", {})
        return bool(logging_cfg.get("enabled", DEFAULT_CONFIG["logging"]["enabled"]))

    def set_played_tracks_logging_enabled(self, enabled: bool) -> None:
        logging_cfg = self._data.setdefault("logging", {})
        logging_cfg["enabled"] = bool(enabled)

    def get_played_tracks_logging_songs_enabled(self) -> bool:
        logging_cfg = self._data.get("logging", {})
        return bool(logging_cfg.get("songs", DEFAULT_CONFIG["logging"]["songs"]))

    def set_played_tracks_logging_songs_enabled(self, enabled: bool) -> None:
        logging_cfg = self._data.setdefault("logging", {})
        logging_cfg["songs"] = bool(enabled)

    def get_played_tracks_logging_spots_enabled(self) -> bool:
        logging_cfg = self._data.get("logging", {})
        return bool(logging_cfg.get("spots", DEFAULT_CONFIG["logging"]["spots"]))

    def set_played_tracks_logging_spots_enabled(self, enabled: bool) -> None:
        logging_cfg = self._data.setdefault("logging", {})
        logging_cfg["spots"] = bool(enabled)

    def get_played_tracks_logging_folder(self) -> Path | None:
        logging_cfg = self._data.get("logging", {})
        raw = logging_cfg.get("folder", DEFAULT_CONFIG["logging"]["folder"])
        if raw in (None, "", False):
            return None
        return Path(str(raw)).expanduser()

    def set_played_tracks_logging_folder(self, folder: Path | str | None) -> None:
        logging_cfg = self._data.setdefault("logging", {})
        if not folder:
            logging_cfg["folder"] = ""
        else:
            logging_cfg["folder"] = str(folder)

    # --- now playing ---
    def get_now_playing_enabled(self) -> bool:
        cfg = self._data.get("now_playing", {})
        return bool(cfg.get("enabled", DEFAULT_CONFIG["now_playing"]["enabled"]))

    def set_now_playing_enabled(self, enabled: bool) -> None:
        cfg = self._data.setdefault("now_playing", {})
        cfg["enabled"] = bool(enabled)

    def get_now_playing_path(self) -> Path | None:
        cfg = self._data.get("now_playing", {})
        raw = cfg.get("path", DEFAULT_CONFIG["now_playing"]["path"])
        if raw in (None, "", False):
            return None
        return Path(str(raw)).expanduser()

    def set_now_playing_path(self, path: Path | str | None) -> None:
        cfg = self._data.setdefault("now_playing", {})
        if not path:
            cfg["path"] = ""
        else:
            cfg["path"] = str(path)

    def get_now_playing_update_on_track_change(self) -> bool:
        cfg = self._data.get("now_playing", {})
        return bool(cfg.get("update_on_track_change", DEFAULT_CONFIG["now_playing"]["update_on_track_change"]))

    def set_now_playing_update_on_track_change(self, enabled: bool) -> None:
        cfg = self._data.setdefault("now_playing", {})
        cfg["update_on_track_change"] = bool(enabled)

    def get_now_playing_update_interval_seconds(self) -> float:
        cfg = self._data.get("now_playing", {})
        raw = cfg.get("update_interval_seconds", DEFAULT_CONFIG["now_playing"]["update_interval_seconds"])
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return float(DEFAULT_CONFIG["now_playing"]["update_interval_seconds"])

    def set_now_playing_update_interval_seconds(self, seconds: float) -> None:
        cfg = self._data.setdefault("now_playing", {})
        try:
            cfg["update_interval_seconds"] = max(0.0, float(seconds))
        except (TypeError, ValueError):
            cfg["update_interval_seconds"] = float(DEFAULT_CONFIG["now_playing"]["update_interval_seconds"])

    def get_now_playing_template(self) -> str:
        cfg = self._data.get("now_playing", {})
        raw = cfg.get("template", DEFAULT_CONFIG["now_playing"]["template"])
        value = str(raw) if raw is not None else ""
        return value if value.strip() else str(DEFAULT_CONFIG["now_playing"]["template"])

    def set_now_playing_template(self, template: str) -> None:
        cfg = self._data.setdefault("now_playing", {})
        cfg["template"] = str(template)

    def get_now_playing_songs_enabled(self) -> bool:
        cfg = self._data.get("now_playing", {})
        return bool(cfg.get("songs", DEFAULT_CONFIG["now_playing"]["songs"]))

    def set_now_playing_songs_enabled(self, enabled: bool) -> None:
        cfg = self._data.setdefault("now_playing", {})
        cfg["songs"] = bool(enabled)

    def get_now_playing_spots_enabled(self) -> bool:
        cfg = self._data.get("now_playing", {})
        return bool(cfg.get("spots", DEFAULT_CONFIG["now_playing"]["spots"]))

    def set_now_playing_spots_enabled(self, enabled: bool) -> None:
        cfg = self._data.setdefault("now_playing", {})
        cfg["spots"] = bool(enabled)

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
                kind_value = entry.get("kind")
                try:
                    kind = PlaylistKind(kind_value)
                except Exception:
                    kind = PlaylistKind.MUSIC
                folder_value = entry.get("folder_path") or entry.get("folder")
                folder_path = Path(folder_value) if folder_value else None
                result.append({"name": name, "slots": normalized_slots, "kind": kind, "folder_path": folder_path})
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
            entry_kind = entry.get("kind", PlaylistKind.MUSIC)
            if isinstance(entry_kind, PlaylistKind):
                kind_value = entry_kind.value
            else:
                try:
                    kind_value = PlaylistKind(entry_kind).value
                except Exception:
                    kind_value = PlaylistKind.MUSIC.value
            normalized_entry: dict[str, Any] = {"name": str(name), "slots": slots, "kind": kind_value}
            folder_path = entry.get("folder_path")
            if folder_path and kind_value == PlaylistKind.FOLDER.value:
                normalized_entry["folder_path"] = str(folder_path)
            normalized.append(normalized_entry)
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

    def get_jingles_device(self) -> str | None:
        devices = self._data.get("devices", {})
        value = None
        if isinstance(devices, dict):
            value = devices.get("jingles")
        if value is None:
            return None
        raw = str(value).strip()
        return raw or None

    def set_jingles_device(self, device_id: str | None) -> None:
        devices = self._data.setdefault("devices", {})
        devices["jingles"] = str(device_id).strip() if device_id else None

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
