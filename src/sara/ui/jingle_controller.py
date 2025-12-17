"""Jingle playback controller independent from playlist logic."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sara.audio.engine import AudioEngine, Player
from sara.core.config import SettingsManager
from sara.core.i18n import gettext as _
from sara.core.media_metadata import extract_metadata
from sara.jingles import JingleSet, load_jingle_set, save_jingle_set, ensure_page_count


@dataclass
class JingleState:
    active_page_index: int = 0


class JingleController:
    """Manages the active jingle page and plays jingles on a dedicated device."""

    def __init__(
        self,
        audio_engine: AudioEngine,
        settings: SettingsManager,
        announce: Callable[[str, str], None],
        *,
        set_path: Path,
        max_overlay_players: int = 4,
    ) -> None:
        self._audio_engine = audio_engine
        self._settings = settings
        self._announce = announce
        self._set_path = set_path
        self._jingle_set: JingleSet = load_jingle_set(set_path)
        ensure_page_count(self._jingle_set, 1)
        self._state = JingleState(active_page_index=0)
        self._device_id: str | None = None
        self._main_player: Player | None = None
        self._overlay_players: list[Player] = []
        self._max_overlay_players = max(1, int(max_overlay_players))
        self._replay_gain_cache: dict[Path, float | None] = {}
        self._player_tokens: dict[int, str] = {}

    @property
    def jingle_set(self) -> JingleSet:
        return self._jingle_set

    @property
    def active_page_index(self) -> int:
        pages = self._jingle_set.normalized_pages()
        if not pages:
            return 0
        return max(0, min(self._state.active_page_index, len(pages) - 1))

    def set_active_page_index(self, index: int) -> None:
        pages = self._jingle_set.normalized_pages()
        if not pages:
            self._state.active_page_index = 0
            return
        self._state.active_page_index = max(0, min(int(index), len(pages) - 1))

    def page_label(self) -> str:
        idx = self.active_page_index
        pages = self._jingle_set.normalized_pages()
        if not pages:
            return _("Page 1")
        page = pages[idx]
        return str(page.name) if page.name else _("Page %d") % (idx + 1)

    def prev_page(self) -> None:
        pages = self._jingle_set.normalized_pages()
        if not pages:
            return
        self._state.active_page_index = (self.active_page_index - 1) % len(pages)
        self._announce("jingles", self.page_label())

    def next_page(self) -> None:
        pages = self._jingle_set.normalized_pages()
        if not pages:
            return
        self._state.active_page_index = (self.active_page_index + 1) % len(pages)
        self._announce("jingles", self.page_label())

    def reload_set(self) -> None:
        self._jingle_set = load_jingle_set(self._set_path)
        ensure_page_count(self._jingle_set, 1)
        self.set_active_page_index(self._state.active_page_index)

    def save_set(self) -> None:
        save_jingle_set(self._set_path, self._jingle_set)

    def set_device_id(self, device_id: str | None) -> None:
        self._device_id = device_id
        self._main_player = None
        self._overlay_players.clear()

    def _resolve_device_id(self) -> str | None:
        if self._device_id:
            return self._device_id
        configured = self._settings.get_jingles_device()
        if configured:
            return configured
        # fallback: first detected device
        devices = self._audio_engine.get_devices()
        return devices[0].id if devices else None

    def _ensure_main_player(self) -> tuple[str, Player] | None:
        device_id = self._resolve_device_id()
        if not device_id:
            return None
        if self._main_player is None:
            self._main_player = self._audio_engine.create_player(device_id)
        return device_id, self._main_player

    def _get_overlay_player(self, device_id: str) -> Player:
        for player in self._overlay_players:
            try:
                if not player.is_active():
                    return player
            except Exception:
                continue
        if len(self._overlay_players) < self._max_overlay_players:
            player = self._audio_engine.create_player_instance(device_id)
            self._overlay_players.append(player)
            return player
        # fallback: reuse the oldest player
        return self._overlay_players[0]

    def play_slot(self, slot_index: int, *, overlay: bool = False) -> bool:
        """Play jingle from current page slot [0..9]."""

        pages = self._jingle_set.normalized_pages()
        if not pages:
            return False
        page = pages[self.active_page_index]
        slots = page.normalized_slots()
        if slot_index < 0 or slot_index >= len(slots):
            return False
        slot = slots[slot_index]
        if not slot.path:
            return False
        path = Path(slot.path)
        if not path.exists():
            self._announce("jingles", _("Missing file: %s") % path.name)
            return False

        replay_gain_db: float | None = slot.replay_gain_db
        if replay_gain_db is None:
            replay_gain_db = self._replay_gain_cache.get(path.resolve())

        fade_seconds = max(0.0, float(self._settings.get_playback_fade_seconds()))
        player_info = self._ensure_main_player()
        if not player_info:
            self._announce("jingles", _("No audio device for jingles"))
            return False
        device_id, main_player = player_info

        player: Player
        if overlay:
            player = self._get_overlay_player(device_id)
        else:
            try:
                if fade_seconds > 0.0 and main_player.is_active():
                    main_player.fade_out(fade_seconds)
                else:
                    main_player.stop()
            except Exception:
                pass
            player = main_player

        item_id = f"jingle-{uuid.uuid4().hex}-{int(time.time() * 1000)}"
        try:
            # Ustaw ReplayGain przed startem, jeśli mamy wartość (bez I/O na ścieżce krytycznej).
            if replay_gain_db is not None:
                player.set_gain_db(replay_gain_db)
            player.play(item_id, str(path), start_seconds=0.0, allow_loop=False)
        except Exception as exc:  # pylint: disable=broad-except
            self._announce("jingles", _("Failed to play jingle: %s") % exc)
            return False

        if replay_gain_db is None:
            self._schedule_replay_gain(player, item_id=item_id, path=path)
        return True

    def _schedule_replay_gain(self, player: Player, *, item_id: str, path: Path) -> None:
        key = id(player)
        self._player_tokens[key] = item_id
        resolved = path.resolve()

        def _worker() -> None:
            gain = None
            try:
                gain = extract_metadata(resolved).replay_gain_db
            except Exception:
                gain = None
            self._replay_gain_cache[resolved] = gain
            if self._player_tokens.get(key) != item_id:
                return
            try:
                player.set_gain_db(gain)
            except Exception:
                return

        import threading

        threading.Thread(target=_worker, daemon=True).start()

    def stop_all(self) -> None:
        players: list[Player] = []
        if self._main_player is not None:
            players.append(self._main_player)
        players.extend(self._overlay_players)
        for player in players:
            try:
                player.stop()
            except Exception:
                continue
