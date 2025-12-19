"""Software mixer that combines multiple sources into a single device stream."""

from __future__ import annotations

import logging
from threading import Event, Thread
from typing import Callable, Optional

from sara.audio.mixer.device import default_stream_factory, detect_device_format
from sara.audio.mixer.render import render_source
from sara.audio.mixer.source_lifecycle import (
    create_source,
    dispose_replaced_source,
    get_sound_file_format,
    open_sound_file,
    resolve_output_samplerate,
)
from sara.audio.mixer.source_manager import MixerSourceManager
from sara.audio.mixer.thread import run_mixer_loop
from sara.audio.mixer.types import (
    MICRO_FADE_SECONDS,
    ZERO_CROSS_WINDOW_SECONDS,
)
from sara.audio.types import AudioDevice

logger = logging.getLogger(__name__)

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy should be available with soundfile
    np = None

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover - sounddevice opcjonalne
    sd = None

try:
    import soundfile as sf
except ImportError:  # pragma: no cover - soundfile opcjonalne
    sf = None


class DeviceMixer:
    """Mixes multiple sources into a single OutputStream."""

    def __init__(
        self,
        device: AudioDevice,
        *,
        block_size: int = 1024,
        stream_factory: Optional[Callable[[float, int], object]] = None,
    ) -> None:
        if np is None:
            raise RuntimeError("numpy is required for DeviceMixer")
        if sf is None:
            raise RuntimeError("soundfile is required for DeviceMixer")

        self.device = device
        self._block_size = block_size
        self._source_manager = MixerSourceManager()
        self._active_event = Event()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._stream_factory = stream_factory
        self._samplerate, self._channels = detect_device_format(sd=sd, device=device, logger=logger)
        self._micro_fade_frames = max(1, int(self._samplerate * MICRO_FADE_SECONDS))
        self._zero_cross_frames = max(1, int(self._samplerate * ZERO_CROSS_WINDOW_SECONDS))
        if self._stream_factory is None:
            self._stream_factory = lambda samplerate, channels: default_stream_factory(
                sd=sd,
                device=self.device,
                block_size=self._block_size,
                samplerate=samplerate,
                channels=channels,
            )

    def _ensure_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        self._active_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None
        sources = self._source_manager.clear()
        for source in sources:
            try:
                source.sound_file.close()
            except Exception:  # pylint: disable=broad-except
                pass
            source.finished_event.set()

    def start_source(
        self,
        source_id: str,
        path: str,
        *,
        start_seconds: float = 0.0,
        gain_db: Optional[float] = None,
        loop: Optional[tuple[float, float]] = None,
        on_progress: Optional[Callable[[str, float], None]] = None,
        on_finished: Optional[Callable[[str], None]] = None,
    ) -> Event:
        sound_file = open_sound_file(path, sf=sf)
        samplerate, channels = get_sound_file_format(
            sound_file,
            default_samplerate=self._samplerate,
            default_channels=self._channels,
        )

        desired_samplerate = resolve_output_samplerate(
            sd=sd,
            device=self.device,
            output_samplerate=self._samplerate,
            output_channels=self._channels,
            file_samplerate=samplerate,
            logger=logger,
        )
        if desired_samplerate != self._samplerate:
            self._samplerate = desired_samplerate
            self._micro_fade_frames = max(1, int(self._samplerate * MICRO_FADE_SECONDS))
            self._zero_cross_frames = max(1, int(self._samplerate * ZERO_CROSS_WINDOW_SECONDS))

        source = create_source(
            source_id=source_id,
            path=path,
            sound_file=sound_file,
            file_samplerate=samplerate,
            file_channels=channels,
            output_samplerate=self._samplerate,
            output_channels=self._channels,
            micro_fade_frames=self._micro_fade_frames,
            zero_cross_frames=self._zero_cross_frames,
            start_seconds=start_seconds,
            gain_db=gain_db,
            loop=loop,
            on_progress=on_progress,
            on_finished=on_finished,
        )

        old = self._source_manager.replace(source)
        if old:
            dispose_replaced_source(old)

        self._active_event.set()
        self._ensure_thread()
        return source.finished_event

    def set_gain_db(self, source_id: str, gain_db: Optional[float]) -> None:
        self._source_manager.set_gain_db(source_id, gain_db)

    def set_loop(self, source_id: str, loop: Optional[tuple[float, float]]) -> None:
        self._source_manager.set_loop(source_id, loop)

    def pause_source(self, source_id: str) -> None:
        self._source_manager.pause(source_id)

    def resume_source(self, source_id: str) -> None:
        if self._source_manager.resume(source_id):
            self._active_event.set()

    def fade_out_source(self, source_id: str, duration: float) -> None:
        if self._source_manager.fade_out(
            source_id,
            duration,
            samplerate=self._samplerate,
            channels=self._channels,
        ):
            self._active_event.set()

    def stop_source(self, source_id: str) -> None:
        source = self._source_manager.pop(source_id)
        if not source:
            return
        try:
            source.sound_file.close()
        except Exception:  # pylint: disable=broad-except
            pass
        if source.on_finished:
            try:
                source.on_finished(source_id)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Błąd callbacku zakończenia miksu: %s", exc)
        source.finished_event.set()

    def update_callbacks(
        self,
        source_id: str,
        *,
        on_progress: Optional[Callable[[str, float], None]] = None,
        on_finished: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._source_manager.update_callbacks(source_id, on_progress=on_progress, on_finished=on_finished)

    def _run(self) -> None:
        run_mixer_loop(
            stream_factory=self._stream_factory,
            samplerate=float(self._samplerate),
            channels=self._channels,
            stop_event=self._stop_event,
            active_event=self._active_event,
            mix_once=self._mix_once,
            finalize_source=self._finalize_source,
            logger=logger,
        )

    def _mix_once(self):
        sources = self._source_manager.snapshot()
        if not sources:
            return None, [], []

        block = np.zeros((self._block_size, self._channels), dtype=np.float32)
        progresses: list[tuple[str, float, Callable[[str, float], None]]] = []
        finished_ids: list[str] = []

        for source in sources:
            data, frames_out, finished = render_source(
                source,
                block_size=self._block_size,
                channels=self._channels,
                micro_fade_frames=self._micro_fade_frames,
            )
            if frames_out:
                block[:frames_out] += data[:frames_out]
            if finished:
                finished_ids.append(source.source_id)
            if source.on_progress and frames_out:
                seconds = source.position_frames / float(source.samplerate or 1)
                progresses.append((source.source_id, seconds, source.on_progress))

        if not finished_ids and not progresses and not block.any():
            self._active_event.clear()
        return block, progresses, finished_ids

    def _finalize_source(self, source_id: str) -> None:
        source = self._source_manager.pop(source_id)
        if not source:
            return
        try:
            source.sound_file.close()
        except Exception:  # pylint: disable=broad-except
            pass
        if source.on_progress:
            try:
                source.on_progress(source_id, source.position_frames / float(source.samplerate or 1))
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Błąd końcowego callbacku postępu mixer: %s", exc)
        if source.on_finished:
            try:
                source.on_finished(source_id)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Błąd callbacku zakończenia mixer: %s", exc)
        source.finished_event.set()
        if self._source_manager.is_empty():
            self._active_event.clear()
