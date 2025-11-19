"""Controllers encapsulating playback/preview state for the main window."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Dict, Iterable, Optional, Tuple

from sara.audio.engine import AudioEngine, Player
from sara.core.config import SettingsManager
from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistModel


logger = logging.getLogger(__name__)


@dataclass
class PlaybackContext:
    player: Player
    path: Path
    device_id: str
    slot_index: int
    intro_seconds: float | None = None
    intro_alert_triggered: bool = False


@dataclass
class PreviewContext:
    player: Player
    device_id: str
    item_path: Path
    finished_event: Event | None = None


class PlaybackController:
    """Manages preview playback and shared playback state."""

    def __init__(
        self,
        audio_engine: AudioEngine,
        settings: SettingsManager,
        announce: Callable[[str, str], None],
    ) -> None:
        self._audio_engine = audio_engine
        self._settings = settings
        self._announce = announce
        self._playback_contexts: Dict[tuple[str, str], PlaybackContext] = {}
        self._auto_mix_state: Dict[tuple[str, str], bool] = {}
        self._preview_context: PreviewContext | None = None
        self._pfl_device_id: str | None = settings.get_pfl_device()

    @property
    def contexts(self) -> Dict[tuple[str, str], PlaybackContext]:
        return self._playback_contexts

    @property
    def auto_mix_state(self) -> Dict[tuple[str, str], bool]:
        return self._auto_mix_state

    @property
    def preview_context(self) -> PreviewContext | None:
        return self._preview_context

    @property
    def pfl_device_id(self) -> str | None:
        return self._pfl_device_id

    def reload_pfl_device(self) -> None:
        new_device = self._settings.get_pfl_device()
        if new_device != self._pfl_device_id:
            self.stop_preview()
        self._pfl_device_id = new_device

    def get_busy_device_ids(self) -> set[str]:
        return {context.device_id for context in self._playback_contexts.values()}

    def stop_playlist(self, playlist_id: str, *, fade_duration: float = 0.0) -> list[tuple[tuple[str, str], PlaybackContext]]:
        keys_to_remove = [key for key in self._playback_contexts if key[0] == playlist_id]
        removed: list[tuple[tuple[str, str], PlaybackContext]] = []
        for key in keys_to_remove:
            self._auto_mix_state.pop(key, None)
            context = self._playback_contexts.pop(key)
            try:
                if fade_duration > 0.0:
                    context.player.fade_out(fade_duration)
                else:
                    context.player.stop()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Failed to stop player: %s", exc)
            try:
                context.player.set_finished_callback(None)
                context.player.set_progress_callback(None)
            except Exception:  # pylint: disable=broad-except
                pass
            removed.append((key, context))
        return removed

    def start_item(
        self,
        playlist: PlaylistModel,
        item: PlaylistItem,
        *,
        start_seconds: float,
        on_finished: Callable[[str], None],
        on_progress: Callable[[str, float], None],
    ) -> PlaybackContext | None:
        key = (playlist.id, item.id)
        context = self._playback_contexts.get(key)
        player = context.player if context else None
        device_id = context.device_id if context else None
        slot_index = context.slot_index if context else None

        if player is None or device_id is None or slot_index is None:
            acquired = self._ensure_player(playlist)
            if acquired is None:
                return None
            player, device_id, slot_index = acquired

        try:
            player.set_finished_callback(on_finished)
            player.set_progress_callback(on_progress)
        except Exception as exc:  # pylint: disable=broad-except
            self._announce("playback_errors", _("Failed to assign playback callbacks: %s") % exc)
            return None

        try:
            player.play(item.id, str(item.path), start_seconds=start_seconds)
        except Exception as exc:  # pylint: disable=broad-except
            player.set_finished_callback(None)
            player.set_progress_callback(None)
            self._announce("playback_errors", _("Playback error: %s") % exc)
            return None

        try:
            player.set_gain_db(item.replay_gain_db)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to set ReplayGain: %s", exc)

        try:
            if item.loop_enabled and item.has_loop():
                player.set_loop(item.loop_start_seconds, item.loop_end_seconds)
            else:
                player.set_loop(None, None)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to configure loop: %s", exc)

        context = PlaybackContext(
            player=player,
            path=item.path,
            device_id=device_id,
            slot_index=slot_index,
            intro_seconds=item.intro_seconds,
        )
        self._playback_contexts[key] = context
        self._auto_mix_state.pop(key, None)
        return context

    def _ensure_player(self, playlist: PlaylistModel) -> tuple[Player, str, int] | None:
        attempts = 0
        missing_devices: set[str] = set()

        while attempts < 2:
            devices = self._audio_engine.get_devices()
            if not devices:
                self._audio_engine.refresh_devices()
                devices = self._audio_engine.get_devices()
                if not devices:
                    self._announce("device", _("No audio devices available"))
                    return None

            device_map = {device.id: device for device in devices}
            busy_devices = self.get_busy_device_ids()
            selection = playlist.select_next_slot(set(device_map.keys()), busy_devices)
            if selection is None:
                if playlist.get_configured_slots():
                    self._announce(
                        "device",
                        _("No configured player for playlist %s is available") % playlist.name,
                    )
                return None

            slot_index, device_id = selection
            device = device_map.get(device_id)
            if device is None:
                missing_devices.add(device_id)
                if playlist.output_slots and 0 <= slot_index < len(playlist.output_slots):
                    playlist.output_slots[slot_index] = None
                    self._settings.set_playlist_outputs(playlist.name, playlist.output_slots)
                    self._settings.save()
                attempts += 1
                self._audio_engine.refresh_devices()
                continue

            try:
                player = self._audio_engine.create_player(device_id)
                return player, device_id, slot_index
            except ValueError:
                attempts += 1
                self._audio_engine.refresh_devices()

        if missing_devices:
            removed_list = ", ".join(sorted(missing_devices))
            self._announce(
                "device",
                _("Unavailable devices for playlist %s: %s") % (playlist.name, removed_list),
            )
        return None

    def get_context(self, playlist_id: str) -> tuple[tuple[str, str], PlaybackContext] | None:
        for key, context in self._playback_contexts.items():
            if key[0] == playlist_id:
                return key, context
        return None

    def clear_auto_mix(self) -> None:
        self._auto_mix_state.clear()

    def clear_playlist_entries(self, playlist_id: str) -> None:
        keys_to_remove = [key for key in self._playback_contexts if key[0] == playlist_id]
        for key in keys_to_remove:
            self._playback_contexts.pop(key, None)
            self._auto_mix_state.pop(key, None)

    def stop_preview(self, *, wait: bool = True) -> None:
        if not self._preview_context:
            return
        context = self._preview_context
        self._preview_context = None
        finished_event = context.finished_event if wait else None
        try:
            context.player.set_loop(None, None)
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            context.player.stop()
        except Exception:  # pylint: disable=broad-except
            pass
        if wait and finished_event:
            try:
                finished_event.wait(timeout=0.5)
            except Exception:  # pylint: disable=broad-except
                pass

    def start_preview(
        self,
        item: PlaylistItem,
        start: float,
        *,
        loop_range: tuple[float, float] | None = None,
    ) -> bool:
        if loop_range is not None and loop_range[1] <= loop_range[0]:
            self._announce("loop", _("Loop end must be greater than start"))
            return False

        self.stop_preview(wait=True)

        pfl_device_id = self._pfl_device_id or self._settings.get_pfl_device()
        if not pfl_device_id:
            self._announce("pfl", _("Configure a PFL device in Options"))
            return False

        known_devices = {device.id for device in self._audio_engine.get_devices()}
        if pfl_device_id not in known_devices:
            self._audio_engine.refresh_devices()
            known_devices = {device.id for device in self._audio_engine.get_devices()}
        if pfl_device_id not in known_devices:
            self._announce("pfl", _("Selected PFL device is not available"))
            return False

        if pfl_device_id in self.get_busy_device_ids():
            self._announce("pfl", _("PFL device is currently in use"))
            return False

        try:
            player = self._audio_engine.create_player(pfl_device_id)
        except Exception as exc:  # pylint: disable=broad-except
            self._announce("pfl", _("Failed to prepare PFL preview: %s") % exc)
            return False

        finished_event: Event | None = None
        try:
            player.set_finished_callback(None)
            player.set_progress_callback(None)
            player.set_gain_db(item.replay_gain_db)
            finished_event = player.play(item.id + ":preview", str(item.path), start_seconds=start)
            if loop_range:
                player.set_loop(loop_range[0], loop_range[1])
            else:
                player.set_loop(None, None)
        except Exception as exc:  # pylint: disable=broad-except
            self._announce("pfl", _("Preview error: %s") % exc)
            try:
                player.stop()
            except Exception:  # pylint: disable=broad-except
                pass
            return False

        self._preview_context = PreviewContext(
            player=player,
            device_id=pfl_device_id,
            item_path=item.path,
            finished_event=finished_event,
        )
        return True

    def update_loop_preview(self, item: PlaylistItem, start: float, end: float) -> bool:
        if end <= start:
            return False
        context = self._preview_context
        if not context or context.item_path != item.path:
            return False
        try:
            context.player.set_loop(start, end)
        except Exception as exc:  # pylint: disable=broad-except
            self._announce("pfl", _("Preview error: %s") % exc)
            return False
        return True


__all__ = ["PlaybackContext", "PlaybackController", "PreviewContext"]
