"""Controllers encapsulating playback/preview state for the main window."""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, TYPE_CHECKING

from sara.audio.engine import AudioDevice, AudioEngine, Player
from sara.core.config import SettingsManager
from sara.core.file_prefetch import warm_file
from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistModel
from sara.ui.playback.context import PlaybackContext
from sara.ui.playback.device_selection import ensure_player as _ensure_player_impl
from sara.ui.playback.mixer_support import PlaybackMixerSupportMixin
from sara.ui.playback.preview import PreviewContext
from sara.ui.playback import start_item as _playback_start_item
from sara.ui.playback import preview as _playback_preview

if TYPE_CHECKING:  # pragma: no cover - tylko dla typowania
    from sara.audio.mixer import DeviceMixer


logger = logging.getLogger(__name__)


@dataclass
class _NextPreload:
    signature: tuple[str | None, Path, float, bool]
    player: Player
    future: Future[bool]


class PlaybackController(PlaybackMixerSupportMixin):
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
        self._preload_enabled = os.environ.get("SARA_ENABLE_PRELOAD", "1") not in {"0", "false", "False"}
        self._preload_warm_bytes = int(os.environ.get("SARA_PRELOAD_WARM_BYTES", str(32 * 1024 * 1024)))
        self._preload_refetch_seconds = float(os.environ.get("SARA_PRELOAD_REFETCH_SECONDS", "60"))
        self._preload_executor: ThreadPoolExecutor | None = None
        self._preload_lock = threading.RLock()
        self._next_preloads: dict[str, _NextPreload] = {}
        self._preloads_closed = False
        self._warm_inflight: dict[Path, Future[int]] = {}
        self._warm_last: dict[Path, float] = {}
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

    @staticmethod
    def supports_mix_trigger(player: Player) -> bool:
        attr = getattr(player, "supports_mix_trigger", None)
        try:
            return bool(attr()) if callable(attr) else bool(attr)
        except Exception:
            return False

    def get_busy_device_ids(self) -> set[str]:
        return {context.device_id for context in self._playback_contexts.values()}

    def stop_playlist(self, playlist_id: str, *, fade_duration: float = 0.0) -> list[tuple[tuple[str, str], PlaybackContext]]:
        self._discard_next_preload(playlist_id)
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

    def update_mix_trigger(
        self,
        playlist_id: str,
        item_id: str,
        *,
        mix_trigger_seconds: float | None,
        on_mix_trigger: Callable[[], None] | None = None,
    ) -> bool:
        """Re-apply mix trigger for an already playing item, if supported by the backend."""
        context = self._playback_contexts.get((playlist_id, item_id))
        if context is None:
            return False
        if not self.supports_mix_trigger(context.player):
            return False
        setter = getattr(context.player, "set_mix_trigger", None)
        if not setter:
            return False
        try:
            setter(mix_trigger_seconds, on_mix_trigger)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug(
                "PlaybackController: failed to update mix trigger playlist=%s item=%s: %s",
                playlist_id,
                item_id,
                exc,
            )
            return False
        return True

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
        return _playback_start_item.start_item_impl(
            self,
            playlist,
            item,
            start_seconds=start_seconds,
            on_finished=on_finished,
            on_progress=on_progress,
            restart_if_playing=restart_if_playing,
            mix_trigger_seconds=mix_trigger_seconds,
            on_mix_trigger=on_mix_trigger,
        )

    def _ensure_player(self, playlist: PlaylistModel) -> tuple[Player, str, int] | None:
        return _ensure_player_impl(self, playlist)

    def get_context(self, playlist_id: str) -> tuple[tuple[str, str], PlaybackContext] | None:
        # prefer the most recently started context for the playlist
        for key, context in reversed(list(self._playback_contexts.items())):
            if key[0] == playlist_id:
                return key, context
        return None

    def clear_auto_mix(self) -> None:
        self._auto_mix_state.clear()

    def clear_playlist_entries(self, playlist_id: str) -> None:
        self._discard_next_preload(playlist_id)
        keys_to_remove = [key for key in self._playback_contexts if key[0] == playlist_id]
        for key in keys_to_remove:
            self._playback_contexts.pop(key, None)
            self._auto_mix_state.pop(key, None)
        self._cleanup_unused_mixers()

    def schedule_next_preload(
        self, playlist: PlaylistModel, *, current_item_id: str | None, sequence: bool = False,
    ) -> None:
        """Best-effort preload of the most likely next track in a playlist.

        This is intended to reduce start latency around mix points on slower storage.
        """
        if not self._preload_enabled or self._preloads_closed:
            self._discard_next_preload(playlist.id)
            return
        next_item = self._resolve_next_preload_item(playlist, current_item_id=current_item_id, sequence=sequence)
        if next_item is None or not next_item.path.exists():
            self._discard_next_preload(playlist.id)
            return

        start_seconds = float(getattr(next_item, "cue_in_seconds", 0.0) or 0.0)
        allow_loop = bool(getattr(next_item, "loop_enabled", False) and getattr(next_item, "has_loop", lambda: False)())
        device_id = self._resolve_preload_device_id(playlist)

        signature = (device_id, next_item.path, start_seconds, allow_loop)
        pending = self._next_preloads.get(playlist.id)
        if pending is not None and pending.signature == signature:
            return
        self._discard_next_preload(playlist.id)
        if device_id:
            try:
                # Osobny player: nie zastępuj grającego/PFL w cache silnika.
                player = self._audio_engine.create_player_instance(device_id)
            except Exception:
                player = None
            if player is not None:
                preloader = getattr(player, "preload", None)
                if callable(preloader):
                    logger.debug("Preload scheduled playlist=%s device=%s path=%s cue=%.3f loop=%s",
                                 playlist.id, device_id, next_item.path, start_seconds, allow_loop)
                    future = self._ensure_preload_executor().submit(
                        self._safe_preload_call,
                        preloader,
                        str(next_item.path),
                        start_seconds=start_seconds,
                        allow_loop=allow_loop,
                    )
                    self._next_preloads[playlist.id] = _NextPreload(signature, player, future)
                    return

        logger.debug("Preload file warmup playlist=%s path=%s", playlist.id, next_item.path)
        self._schedule_file_warmup(next_item.path)

    def _discard_next_preload(self, playlist_id: str) -> None:
        pending = self._next_preloads.pop(playlist_id, None)
        if pending is not None:
            pending.future.cancel()
            # Jeden executor: zwolnienie zawsze PO ewentualnym trwającym otwarciu,
            # nigdy join/future.result w GUI. Bariera EBU obejmuje też sprzątanie.
            self._ensure_preload_executor().submit(pending.player.stop)
            logger.debug("Preload discarded playlist=%s path=%s", playlist_id, pending.signature[1])

    def _take_preloaded_player(self, playlist_id: str, device_id: str) -> Player | None:
        pending = self._next_preloads.get(playlist_id)
        if (pending is not None and pending.signature[0] == device_id
                and pending.future.done() and not pending.future.cancelled()
                and pending.future.result()):
            self._next_preloads.pop(playlist_id)
            # create_player() jest fabryką, NIE odczytem cache. Przekaż dokładnie
            # tę instancję, która ma gotowy strumień; play sprawdzi path/cue/loop.
            self._audio_engine._players[device_id] = pending.player
            logger.debug("Preload handed off playlist=%s device=%s path=%s",
                         playlist_id, device_id, pending.signature[1])
            return pending.player
        self._discard_next_preload(playlist_id)
        logger.debug("Preload miss playlist=%s device=%s", playlist_id, device_id)
        return None

    def preloaded_paths(self) -> list[Path]:
        """Ścieżki chronione przed zapisem tagów także przed publikacją uchwytu."""
        return [pending.signature[1] for pending in self._next_preloads.values()]

    def close_preloads(self) -> None:
        self._preloads_closed = True
        for playlist_id in list(self._next_preloads):
            self._discard_next_preload(playlist_id)
        if self._preload_executor is not None:
            self._preload_executor.shutdown(wait=False)

    def _ensure_preload_executor(self) -> ThreadPoolExecutor:
        with self._preload_lock:
            if self._preload_executor is None:
                self._preload_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sara-preload")
            return self._preload_executor

    def _safe_preload_call(self, preloader, source_path: str, *, start_seconds: float, allow_loop: bool) -> bool:
        started = time.perf_counter()
        try:
            ready = bool(preloader(source_path, start_seconds=start_seconds, allow_loop=allow_loop))
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Preload failed for %s: %s", source_path, exc)
            ready = False
        logger.debug("Preload finished path=%s ready=%s elapsed_ms=%.3f",
                     source_path, ready, (time.perf_counter() - started) * 1000)
        return ready

    def _schedule_file_warmup(self, path: Path) -> None:
        max_bytes = int(self._preload_warm_bytes)
        if max_bytes <= 0:
            return
        resolved = Path(path)
        now = time.monotonic()
        with self._preload_lock:
            last = self._warm_last.get(resolved)
            if last is not None and (now - last) < self._preload_refetch_seconds:
                return
            inflight = self._warm_inflight.get(resolved)
            if inflight is not None and not inflight.done():
                return
            future = self._ensure_preload_executor().submit(warm_file, resolved, max_bytes=max_bytes)
            self._warm_inflight[resolved] = future
            self._warm_last[resolved] = now
        future.add_done_callback(lambda _f, key=resolved: self._drop_warm_future(key))

    def _drop_warm_future(self, path: Path) -> None:
        with self._preload_lock:
            self._warm_inflight.pop(path, None)

    def _resolve_next_preload_item(
        self,
        playlist: PlaylistModel,
        *,
        current_item_id: str | None,
        sequence: bool = False,
    ) -> PlaylistItem | None:
        if sequence:
            # Automiks odtwarza kolejność z zawijaniem, również pozycje PLAYED.
            items = playlist.items
            start_index = playlist.index_of(current_item_id) if current_item_id else -1
            for offset in range(1, len(items) + 1):
                candidate = items[(start_index + offset) % len(items)]
                if candidate.id != current_item_id and candidate.status is not PlaylistItemStatus.PLAYING:
                    return candidate
            return None
        selected_id = playlist.next_selected_item_id()
        if selected_id and selected_id != current_item_id:
            item = playlist.get_item(selected_id)
            if item is not None:
                return item

        items = playlist.items
        total = len(items)
        if total == 0:
            return None
        start_index = playlist.index_of(current_item_id) if current_item_id else -1
        for offset in range(1, total + 1):
            idx = (start_index + offset) % total
            candidate = items[idx]
            if current_item_id and candidate.id == current_item_id:
                continue
            if candidate.status is PlaylistItemStatus.PLAYING:
                continue
            if candidate.status in (PlaylistItemStatus.PENDING, PlaylistItemStatus.PAUSED):
                return candidate
        return None

    def _resolve_preload_device_id(self, playlist: PlaylistModel) -> str | None:
        configured = [slot for slot in playlist.get_configured_slots() if slot]
        if not configured:
            return None
        try:
            available = {device.id for device in self._audio_engine.get_devices()}
        except Exception:
            return configured[0]
        if not available:
            return configured[0]
        try:
            selection = playlist.peek_next_slot(available, self.get_busy_device_ids())
        except Exception:
            selection = None
        if selection is not None:
            return selection[1]
        return configured[0]

    def stop_preview(self, *, wait: bool = True) -> None:
        _playback_preview.stop_preview(self, wait=wait)

    def start_preview(
        self,
        item: PlaylistItem,
        start: float,
        *,
        loop_range: tuple[float, float] | None = None,
    ) -> bool:
        return _playback_preview.start_preview(self, item, start, loop_range=loop_range)

    def start_mix_preview(
        self,
        current_item: PlaylistItem,
        next_item: PlaylistItem,
        *,
        mix_at_seconds: float,
        pre_seconds: float = 4.0,
        fade_seconds: float = 0.0,
        current_base_cue: float | None = None,
        current_effective_duration: float | None = None,
        next_cue_override: float | None = None,
    ) -> bool:
        """Preview crossfade/mix between current and next track on the PFL device.

        Używa dwóch playerów na tym samym urządzeniu PFL. Player A startuje kilka sekund
        przed punktem miksu, player B startuje dokładnie w punkcie mix_at_seconds (relatywnie
        do startu A). Fade A jest stosowany opcjonalnie.
        """
        return _playback_preview.start_mix_preview(
            self,
            current_item,
            next_item,
            mix_at_seconds=mix_at_seconds,
            pre_seconds=pre_seconds,
            fade_seconds=fade_seconds,
            current_base_cue=current_base_cue,
            current_effective_duration=current_effective_duration,
            next_cue_override=next_cue_override,
        )

    def update_loop_preview(self, item: PlaylistItem, start: float, end: float) -> bool:
        return _playback_preview.update_loop_preview(self, item, start, end)


__all__ = ["PlaybackContext", "PlaybackController", "PreviewContext"]
