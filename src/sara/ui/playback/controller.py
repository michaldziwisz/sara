"""Controllers encapsulating playback/preview state for the main window."""

from __future__ import annotations

import logging
from typing import Callable, Dict, TYPE_CHECKING

from sara.audio.engine import AudioDevice, AudioEngine, Player
from sara.core.config import SettingsManager
from sara.core.playlist import PlaylistItem, PlaylistModel
from sara.ui.playback.context import PlaybackContext
from sara.ui.playback.device_selection import ensure_player as _ensure_player_impl
from sara.ui.playback.mixer_support import PlaybackMixerSupportMixin
from sara.ui.playback.preview import PreviewContext
from sara.ui.playback import start_item as _playback_start_item
from sara.ui.playback import preview as _playback_preview

if TYPE_CHECKING:  # pragma: no cover - tylko dla typowania
    from sara.audio.mixer import DeviceMixer


logger = logging.getLogger(__name__)


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
        keys_to_remove = [key for key in self._playback_contexts if key[0] == playlist_id]
        for key in keys_to_remove:
            self._playback_contexts.pop(key, None)
            self._auto_mix_state.pop(key, None)
        self._cleanup_unused_mixers()

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
            current_effective_duration=current_effective_duration,
            next_cue_override=next_cue_override,
        )

    def update_loop_preview(self, item: PlaylistItem, start: float, end: float) -> bool:
        return _playback_preview.update_loop_preview(self, item, start, end)


__all__ = ["PlaybackContext", "PlaybackController", "PreviewContext"]
