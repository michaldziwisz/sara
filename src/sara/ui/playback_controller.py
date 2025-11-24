"""Controllers encapsulating playback/preview state for the main window."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Dict, Iterable, Optional, Tuple, TYPE_CHECKING

from sara.audio.engine import AudioDevice, AudioEngine, Player, BackendType
from sara.core.config import SettingsManager
from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistModel, PlaylistItemStatus

if TYPE_CHECKING:  # pragma: no cover - tylko dla typowania
    from sara.audio.mixer import DeviceMixer


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
    players: list[Player]
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
        mixer_factory: Callable[[AudioDevice], "DeviceMixer"] | None = None,
    ) -> None:
        self._audio_engine = audio_engine
        self._settings = settings
        self._announce = announce
        self._playback_contexts: Dict[tuple[str, str], PlaybackContext] = {}
        self._auto_mix_state: Dict[tuple[str, str], bool] = {}
        self._preview_context: PreviewContext | None = None
        self._pfl_device_id: str | None = settings.get_pfl_device()
        self._mixers: Dict[str, "DeviceMixer"] = {}
        self._mixer_factory = mixer_factory or self._default_mixer_factory
        # upewnij się, że cache playerów jest świeży po zmianach backendu
        try:
            self._audio_engine.stop_all()
        except Exception:
            pass

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
        self._cleanup_unused_mixers()
        return removed

    def start_item(
        self,
        playlist: PlaylistModel,
        item: PlaylistItem,
        *,
        start_seconds: float,
        on_finished: Callable[[str], None],
        on_progress: Callable[[str, float], None],
        restart_if_playing: bool = False,
        mix_trigger_seconds: float | None = None,
        on_mix_trigger: Callable[[], None] | None = None,
    ) -> PlaybackContext | None:
        try:
            return self._start_item_impl(
                playlist,
                item,
                start_seconds=start_seconds,
                on_finished=on_finished,
                on_progress=on_progress,
                restart_if_playing=restart_if_playing,
                mix_trigger_seconds=mix_trigger_seconds,
                on_mix_trigger=on_mix_trigger,
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "PlaybackController: unhandled error starting item playlist=%s item_id=%s",
                getattr(playlist, "name", playlist.id),
                item.id,
            )
            raise

    # Wydzielona implementacja pozwala zalogować traceback bez rozwijania głównej sygnatury.
    def _start_item_impl(
        self,
        playlist: PlaylistModel,
        item: PlaylistItem,
        *,
        start_seconds: float,
        on_finished: Callable[[str], None],
        on_progress: Callable[[str, float], None],
        restart_if_playing: bool = False,
        mix_trigger_seconds: float | None = None,
        on_mix_trigger: Callable[[], None] | None = None,
    ) -> PlaybackContext | None:
        # Nie uruchamiaj ponownie utworu już zagranych (PLAYED), chyba że wyraźnie prosimy o restart.
        if item.status is PlaylistItemStatus.PLAYED:
            if restart_if_playing:
                logger.debug(
                    "PlaybackController: restarting item marked PLAYED playlist=%s item=%s",
                    playlist.name,
                    item.id,
                )
                # pozwól na ponowne zagranie jakby był świeży
                item.status = PlaylistItemStatus.PENDING
            else:
                logger.debug(
                    "PlaybackController: skipping item already PLAYED playlist=%s item=%s",
                    playlist.name,
                    item.id,
                )
                return None
        logger.info(
            "PlaybackController: start_item playlist=%s item_id=%s title=%s slots=%s busy=%s",
            playlist.name,
            item.id,
            getattr(item, "title", item.id),
            playlist.get_configured_slots(),
            self.get_busy_device_ids(),
        )
        key = (playlist.id, item.id)
        context = self._playback_contexts.get(key)
        player = context.player if context else None
        device_id = context.device_id if context else None
        slot_index = context.slot_index if context else None

        if (
            player is not None
            and device_id is not None
            and slot_index is not None
            and item.status is PlaylistItemStatus.PLAYING
        ):
            if restart_if_playing:
                logger.debug(
                    "PlaybackController: restarting item already playing on device=%s slot=%s",
                    device_id,
                    slot_index,
                )
                try:
                    player.stop()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("Failed to stop player for restart: %s", exc)
            else:
                logger.debug(
                    "PlaybackController: item already playing, reusing existing player device=%s slot=%s",
                    device_id,
                    slot_index,
                )
                return context
        # Jeśli utwór był PLAYED i automix włączony – nie restartuj go, wybierz inny.
        if (
            player is not None
            and device_id is not None
            and slot_index is not None
            and item.status is PlaylistItemStatus.PLAYED
            and self._settings.get_alternate_play_next()
        ):
            logger.debug("PlaybackController: skipping PLAYED item in automix/play-next flow")
            return None

        if player is None or device_id is None or slot_index is None:
            acquired = self._ensure_player(playlist)
            if acquired is None:
                logger.error("PlaybackController: no player acquired for playlist=%s item=%s", playlist.name, item.id)
                return None
            player, device_id, slot_index = acquired

            try:
                player.set_finished_callback(on_finished)
                player.set_progress_callback(on_progress)
            except Exception as exc:  # pylint: disable=broad-except
                self._announce("playback_errors", _("Failed to assign playback callbacks: %s") % exc)
                logger.debug("PlaybackController: callback assignment failed device=%s slot=%s: %s", device_id, slot_index, exc)
                return None

        def _do_play(p: Player) -> None:
            # wyzeruj ewentualne poprzednie ustawienia pętli zanim wystartujemy nowy utwór
            if hasattr(p, "set_loop") and not (item.loop_enabled and item.has_loop()):
                try:
                    p.set_loop(None, None)
                except Exception:
                    pass
            p.play(
                item.id,
                str(item.path),
                start_seconds=start_seconds,
                # pozwól SAMPLE_LOOP, jeśli faktycznie mamy pętlę (dla ASIO też),
                # reszta i tak jest kontrolowana markerami/guardem
                allow_loop=bool(item.loop_enabled and item.has_loop()),
                # mikser/punkty miksu: użyj bardziej precyzyjnego wyzwalacza (ms), jeśli dostępny
                mix_trigger_seconds=mix_trigger_seconds,
                on_mix_trigger=on_mix_trigger,
            )

        # Ustaw ReplayGain przed startem, żeby uniknąć „głośnego pierwszego uderzenia”
        try:
            player.set_gain_db(item.replay_gain_db)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to set ReplayGain: %s", exc)

        try:
            _do_play(player)
        except Exception as exc:  # pylint: disable=broad-except
            player.set_finished_callback(None)
            player.set_progress_callback(None)
            logger.exception(
                "PlaybackController: play failed playlist=%s item=%s device=%s slot=%s err=%s",
                playlist.name,
                item.title,
                device_id,
                slot_index,
                exc,
            )
            # jeśli player jest stary/niekompletny, usuń cache i spróbuj raz jeszcze
            try:
                self._audio_engine._players.pop(device_id, None)  # pylint: disable=protected-access
            except Exception:
                pass
            try:
                player = self._audio_engine.create_player(device_id)
                player.set_finished_callback(on_finished)
                player.set_progress_callback(on_progress)
                # ponownie ustaw RG przed startem
                player.set_gain_db(item.replay_gain_db)
                _do_play(player)
            except Exception as retry_exc:  # pylint: disable=broad-except
                logger.exception("PlaybackController: retry after player refresh failed: %s", retry_exc)
                self._announce("playback_errors", f"{retry_exc}")
                return None

        try:
            if hasattr(player, "set_loop"):
                if item.loop_enabled and item.has_loop():
                    player.set_loop(item.loop_start_seconds, item.loop_end_seconds)
                else:
                    player.set_loop(None, None)
            else:
                logger.debug("Loop not supported by player %s", type(player))
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
        use_mixer = self._should_use_mixer(playlist)

        def pick_fallback(device_map: dict[str, AudioDevice], busy_devices: set[str]) -> tuple[int, str] | None:
            # prefer BASS not busy -> any not busy -> busy BASS -> any
            def score(dev: AudioDevice) -> tuple[int, bool]:
                return (0 if dev.backend is BackendType.BASS else 1, dev.id in busy_devices)

            sorted_devices = sorted(device_map.values(), key=score)
            for dev in sorted_devices:
                if dev.id in busy_devices:
                    continue
                return (0, dev.id)
            if sorted_devices:
                return (0, sorted_devices[0].id)
            return None

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
                selection = pick_fallback(device_map, busy_devices)
                if selection is None:
                    logger.error(
                        "PlaybackController: no available slot for playlist=%s configured_slots=%s available=%s busy=%s",
                        playlist.name,
                        playlist.get_configured_slots(),
                        list(device_map.keys()),
                        list(busy_devices),
                    )
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
                logger.debug(
                    "PlaybackController: device %s missing for playlist=%s, refreshing devices (attempt %s)",
                    device_id,
                    playlist.name,
                    attempts,
                )
                continue
            logger.debug(
                "PlaybackController: selected device %s backend=%s slot=%s use_mixer=%s configured_slots=%s busy=%s",
                device_id,
                device.backend if hasattr(device, "backend") else "?",
                slot_index,
                use_mixer,
                playlist.get_configured_slots(),
                busy_devices,
            )

            try:
                # Jeśli backend to BASS lub mixer nie jest dostępny, graj bezpośrednio
                effective_use_mixer = use_mixer and device.backend not in (BackendType.BASS, BackendType.BASS_ASIO)
                player: Player
                if effective_use_mixer:
                    try:
                        mixer = self._get_or_create_mixer(device)
                        MixerPlayer = self._get_mixer_player_class()
                        player = MixerPlayer(mixer)
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.warning("Mixer unavailable for %s, falling back to direct player: %s", device_id, exc)
                        effective_use_mixer = False
                if not effective_use_mixer:
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

    def _get_mixer_classes(self):
        from sara.audio.mixer import DeviceMixer, MixerPlayer

        return DeviceMixer, MixerPlayer

    def _get_mixer_player_class(self):
        _, MixerPlayer = self._get_mixer_classes()
        return MixerPlayer

    def _default_mixer_factory(self, device: AudioDevice):
        DeviceMixer, _ = self._get_mixer_classes()
        return DeviceMixer(device)

    def _get_or_create_mixer(self, device: AudioDevice):
        mixer = self._mixers.get(device.id)
        if mixer:
            return mixer
        mixer = self._mixer_factory(device)
        self._mixers[device.id] = mixer
        return mixer

    def _cleanup_unused_mixers(self) -> None:
        active_devices = {context.device_id for context in self._playback_contexts.values()}
        stale = [device_id for device_id in self._mixers if device_id not in active_devices]
        for device_id in stale:
            mixer = self._mixers.pop(device_id)
            try:
                mixer.close()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Nie udało się zamknąć miksera %s: %s", device_id, exc)

    def _should_use_mixer(self, playlist: PlaylistModel) -> bool:
        slots = [slot for slot in playlist.get_configured_slots() if slot]
        return len(slots) <= 1

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
        self._cleanup_unused_mixers()

    def stop_preview(self, *, wait: bool = True) -> None:
        if not self._preview_context:
            return
        context = self._preview_context
        self._preview_context = None
        finished_event = context.finished_event if wait else None
        # sygnalizuj wątkom podglądu, że mają się zatrzymać
        try:
            if context.finished_event:
                context.finished_event.set()
        except Exception:  # pylint: disable=broad-except
            pass
        for player in context.players:
            try:
                if hasattr(player, "set_loop"):
                    player.set_loop(None, None)
            except Exception:  # pylint: disable=broad-except
                pass
            try:
                player.stop()
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
        logger.debug(
            "PlaybackController: start_preview item=%s start=%.3f loop=%s device=%s",
            getattr(item, "title", item.id),
            start,
            loop_range,
            self._pfl_device_id,
        )
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
            finished_event = player.play(
                item.id + ":preview",
                str(item.path),
                start_seconds=start,
                allow_loop=True,
            )
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
            players=[player],
            device_id=pfl_device_id,
            item_path=item.path,
            finished_event=finished_event,
        )
        return True

    def start_mix_preview(
        self,
        current_item: PlaylistItem,
        next_item: PlaylistItem,
        *,
        mix_at_seconds: float,
        pre_seconds: float = 4.0,
        fade_seconds: float = 0.0,
    ) -> bool:
        """Preview crossfade/mix between current and next track on the PFL device.

        Używa dwóch playerów na tym samym urządzeniu PFL. Player A startuje kilka sekund
        przed punktem miksu, player B startuje dokładnie w punkcie mix_at_seconds (relatywnie
        do startu A). Fade A jest stosowany opcjonalnie.
        """
        self.stop_preview(wait=False)

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

        try:
            player_a = self._audio_engine.create_player(pfl_device_id)
            player_b = self._audio_engine.create_player(pfl_device_id)
        except Exception as exc:  # pylint: disable=broad-except
            self._announce("pfl", _("Failed to prepare mix preview: %s") % exc)
            return False

        start_a = max(0.0, mix_at_seconds - pre_seconds)
        delay_b = max(0.0, mix_at_seconds - start_a)
        remaining_current = max(0.0, (current_item.effective_duration_seconds) - mix_at_seconds)
        fade_len = min(max(0.0, fade_seconds), remaining_current) if remaining_current > 0 else 0.0
        next_start = next_item.cue_in_seconds or 0.0

        logger.debug(
            "PFL mix preview: current=%s next=%s mix_at=%.3f pre=%.3f fade=%.3f cue_next=%.3f",
            current_item.title,
            next_item.title,
            mix_at_seconds,
            pre_seconds,
            fade_len,
            next_start,
        )

        stop_event = Event()

        # jeśli trigger w przeszłości, odpal B natychmiast i skróć pre-window
        if delay_b <= 0:
            delay_b = 0.0
            start_a = max(0.0, mix_at_seconds - pre_seconds)

        def _start_b_and_fade() -> None:
            if delay_b > 0:
                stop_event.wait(timeout=delay_b)
            if stop_event.is_set():
                return
            try:
                player_b.play(next_item.id, str(next_item.path), start_seconds=next_start, allow_loop=False)
            except Exception:
                return
            if fade_len > 0:
                try:
                    player_a.fade_out(fade_len)
                except Exception:
                    pass

        try:
            player_a.play(current_item.id, str(current_item.path), start_seconds=start_a, allow_loop=False)
        except Exception as exc:  # pylint: disable=broad-except
            self._announce("pfl", _("Failed to start mix preview: %s") % exc)
            return False

        threading.Thread(target=_start_b_and_fade, daemon=True).start()

        # auto-stop po krótkim oknie odsłuchu (pre + fade + zapas)
        total_preview = pre_seconds + max(fade_len, 0.0) + 4.0
        
        def _auto_stop() -> None:
            stop_event.wait(timeout=total_preview)
            self.stop_preview(wait=False)

        threading.Thread(target=_auto_stop, daemon=True).start()

        self._preview_context = PreviewContext(
            players=[player_a, player_b],
            device_id=pfl_device_id,
            item_path=current_item.path,
            finished_event=stop_event,
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
