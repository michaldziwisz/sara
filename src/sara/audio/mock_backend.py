"""Mock audio backend used by tests and fallback flows."""

from __future__ import annotations

import logging
from threading import Timer
from typing import Callable, List, Optional

from sara.audio.types import AudioDevice, BackendType, Player


logger = logging.getLogger(__name__)


class MockPlayer:
    """Zastępczy player do wczesnych testów bez realnego audio."""

    def __init__(self, device: AudioDevice):
        self.device = device
        self._current_item: Optional[str] = None
        self._timer: Optional[Timer] = None
        self._on_finished: Optional[Callable[[str], None]] = None
        self._on_progress: Optional[Callable[[str, float], None]] = None
        self._progress_seconds: float = 0.0
        self._gain_db: Optional[float] = None

        self._loop_start: float = 0.0
        self._loop_end: Optional[float] = None

    def play(
        self,
        playlist_item_id: str,
        source_path: str,
        *,
        start_seconds: float = 0.0,
        allow_loop: bool = True,
        mix_trigger_seconds: float | None = None,
        on_mix_trigger: Callable[[], None] | None = None,
    ) -> Optional[object]:  # noqa: D401
        del allow_loop, mix_trigger_seconds, on_mix_trigger  # unused in mock
        self.stop()
        self._current_item = playlist_item_id
        logger.info("[MOCK] Odtwarzanie %s na %s (%s)", source_path, self.device.name, playlist_item_id)
        self._progress_seconds = max(0.0, start_seconds)
        self._timer = Timer(0.1, self._tick)
        self._timer.start()
        return None

    def is_active(self) -> bool:
        return bool(self._current_item)

    def pause(self) -> None:  # noqa: D401
        if self._current_item:
            logger.info("[MOCK] Pauza %s", self._current_item)

    def stop(self) -> None:  # noqa: D401
        item_id = self._current_item
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if self._current_item:
            logger.info("[MOCK] Stop %s", self._current_item)
            self._current_item = None
        if self._on_progress and item_id:
            try:
                self._on_progress(item_id, 0.0)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Błąd callbacku postępu: %s", exc)

    def fade_out(self, duration: float) -> None:  # noqa: D401
        if self._current_item:
            logger.info("[MOCK] Fade out %s w %.2fs", self._current_item, duration)
            self.stop()

    def set_finished_callback(self, callback: Optional[Callable[[str], None]]) -> None:  # noqa: D401
        self._on_finished = callback

    def set_progress_callback(self, callback: Optional[Callable[[str, float], None]]) -> None:  # noqa: D401
        self._on_progress = callback

    def set_mix_trigger(
        self,
        mix_trigger_seconds: Optional[float],
        on_mix_trigger: Optional[Callable[[], None]],
    ) -> None:
        # Mock nie implementuje realnych triggerów miksu; zapamiętaj callback dla zgodności.
        del mix_trigger_seconds  # unused
        self._on_mix_trigger = on_mix_trigger  # type: ignore[attr-defined]

    def set_gain_db(self, gain_db: Optional[float]) -> None:  # noqa: D401
        self._gain_db = gain_db

    def set_loop(self, start_seconds: Optional[float], end_seconds: Optional[float]) -> None:  # noqa: D401
        if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
            self._loop_end = None
            self._loop_start = 0.0
            return
        self._loop_start = max(0.0, start_seconds)
        self._loop_end = end_seconds

    def supports_mix_trigger(self) -> bool:
        return False

    # kompatybilność – w prawdziwym playerze wywoływane przy play
    def _apply_loop_settings(self) -> None:
        return

    def _tick(self) -> None:
        if not self._current_item:
            return
        self._progress_seconds += 0.1
        if self._on_progress:
            self._on_progress(self._current_item, self._progress_seconds)
        # zakończ po 1 sekundzie symulacji, żeby testy kończyły się szybko, chyba że działa pętla
        if self._loop_end is not None and self._progress_seconds >= self._loop_end:
            self._progress_seconds = self._loop_start
            if self._on_progress:
                self._on_progress(self._current_item, self._progress_seconds)
            self._timer = Timer(0.1, self._tick)
            self._timer.start()
        else:
            if self._progress_seconds >= 1.0 and self._loop_end is None:
                if self._on_finished:
                    self._on_finished(self._current_item)
                self._current_item = None
                self._timer = None
            else:
                self._timer = Timer(0.1, self._tick)
                self._timer.start()


class MockBackendProvider:
    """Backend dla testów E2E bez realnych urządzeń audio."""

    backend = BackendType.WASAPI

    def __init__(self, label: str = "Mock Device") -> None:
        self._label = label

    def list_devices(self) -> List[AudioDevice]:
        return [
            AudioDevice(
                id="mock:default",
                name=self._label,
                backend=self.backend,
                raw_index=None,
                is_default=True,
            )
        ]

    def create_player(self, device: AudioDevice) -> Player:
        return MockPlayer(device)

