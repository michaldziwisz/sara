"""Player-compatible adapter around `DeviceMixer`."""

from __future__ import annotations

from threading import Event
from typing import Callable, Optional

from sara.audio.device_mixer import DeviceMixer


class MixerPlayer:
    """Player-compatible adapter around DeviceMixer."""

    def __init__(self, mixer: DeviceMixer):
        self._mixer = mixer
        self._source_id: Optional[str] = None
        self._finished_cb: Optional[Callable[[str], None]] = None
        self._progress_cb: Optional[Callable[[str, float], None]] = None

    def play(
        self,
        playlist_item_id: str,
        source_path: str,
        *,
        start_seconds: float = 0.0,
        mix_trigger_seconds: float | None = None,
        on_mix_trigger: Callable[[], None] | None = None,
    ) -> Event:
        self._source_id = playlist_item_id
        return self._mixer.start_source(
            playlist_item_id,
            source_path,
            start_seconds=start_seconds,
            on_progress=self._progress_cb,
            on_finished=self._finished_cb,
        )

    def pause(self) -> None:
        if self._source_id:
            self._mixer.pause_source(self._source_id)

    def stop(self) -> None:
        if self._source_id:
            self._mixer.stop_source(self._source_id)
            self._source_id = None

    def fade_out(self, duration: float) -> None:
        if self._source_id:
            self._mixer.fade_out_source(self._source_id, duration)

    def set_finished_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        self._finished_cb = callback
        if self._source_id:
            self._mixer.update_callbacks(self._source_id, on_finished=callback, on_progress=self._progress_cb)

    def set_progress_callback(self, callback: Optional[Callable[[str, float], None]]) -> None:
        self._progress_cb = callback
        if self._source_id:
            self._mixer.update_callbacks(self._source_id, on_progress=callback, on_finished=self._finished_cb)

    def set_mix_trigger(
        self,
        mix_trigger_seconds: float | None,
        on_mix_trigger: Callable[[], None] | None,
    ) -> None:
        # DeviceMixer nie obsługuje hardware'owego triggera miksu – metoda dla kompatybilności.
        return

    def set_gain_db(self, gain_db: Optional[float]) -> None:
        if self._source_id:
            self._mixer.set_gain_db(self._source_id, gain_db)

    def set_loop(self, start_seconds: Optional[float], end_seconds: Optional[float]) -> None:
        if self._source_id is None:
            return
        if start_seconds is None or end_seconds is None:
            self._mixer.set_loop(self._source_id, None)
            return
        self._mixer.set_loop(self._source_id, (start_seconds, end_seconds))

    def supports_mix_trigger(self) -> bool:
        return False

