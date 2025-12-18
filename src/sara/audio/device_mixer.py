"""Software mixer that combines multiple sources into a single device stream."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Callable, Dict, Optional

from sara.audio.engine import AudioDevice, _resample_to_length

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

# Small fade to mask offset/loop clicks
MICRO_FADE_SECONDS = 0.004
# Window to look for a nearby zero-crossing when starting playback
ZERO_CROSS_WINDOW_SECONDS = 0.005


class NullOutputStream:
    """Fallback OutputStream used when sounddevice is not available."""

    def __init__(self, samplerate: float, channels: int, writes: Optional[list] = None):
        self.samplerate = samplerate
        self.channels = channels
        self._writes = writes

    def write(self, data) -> None:  # pragma: no cover - trivial
        if self._writes is not None and np is not None:
            self._writes.append(np.array(data, copy=True))

    def __enter__(self) -> "NullOutputStream":  # pragma: no cover - trivial
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # pragma: no cover - trivial
        return False


@dataclass
class MixerSource:
    source_id: str
    path: Path
    sound_file: "sf.SoundFile"
    samplerate: int
    channels: int
    resample_ratio: float
    buffer: np.ndarray
    gain: float = 1.0
    loop_range: Optional[tuple[int, int]] = None
    fade_in_remaining: int = 0
    fade_out_remaining: int = 0
    pending_fade_in: int = 0
    paused: bool = False
    stop_requested: bool = False
    position_frames: int = 0
    finished_event: Event = field(default_factory=Event)
    on_progress: Optional[Callable[[str, float], None]] = None
    on_finished: Optional[Callable[[str], None]] = None


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
        self._sources: Dict[str, MixerSource] = {}
        self._lock = Lock()
        self._active_event = Event()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._stream_factory = stream_factory
        self._samplerate, self._channels = self._detect_device_format(device)
        self._micro_fade_frames = max(1, int(self._samplerate * MICRO_FADE_SECONDS))
        self._zero_cross_frames = max(1, int(self._samplerate * ZERO_CROSS_WINDOW_SECONDS))
        if self._stream_factory is None:
            self._stream_factory = self._default_stream_factory

    def _detect_device_format(self, device: AudioDevice) -> tuple[int, int]:
        samplerate = 48000
        channels = 2
        if sd is None or device.raw_index is None:
            return samplerate, channels
        try:
            info = sd.query_devices(device.raw_index)
            samplerate = int(info.get("default_samplerate") or samplerate)
            channels = int(info.get("max_output_channels") or channels)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Nie udało się pobrać parametrów urządzenia %s: %s", device.name, exc)
        channels = max(1, channels)
        return samplerate, channels

    def _default_stream_factory(self, samplerate: float, channels: int):
        if sd is None:
            return NullOutputStream(samplerate, channels)
        kwargs = {
            "device": self.device.raw_index,
            "samplerate": samplerate,
            "channels": channels,
            "dtype": "float32",
            "blocksize": self._block_size,
        }
        return sd.OutputStream(**kwargs)

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
        with self._lock:
            sources = list(self._sources.values())
            self._sources.clear()
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
        sound_file = sf.SoundFile(path, mode="r")
        samplerate = int(sound_file.samplerate or self._samplerate)
        channels = int(sound_file.channels or self._channels)

        if sd is not None and self.device.raw_index is not None:
            try:
                sd.check_output_settings(
                    device=self.device.raw_index,
                    samplerate=float(self._samplerate),
                    channels=self._channels,
                )
            except Exception:  # pylint: disable=broad-except
                logger.debug(
                    "Urządzenie %s nie wspiera %s Hz - fallback do %s",
                    self.device.name,
                    self._samplerate,
                    samplerate,
                )
                self._samplerate = samplerate
                self._micro_fade_frames = max(1, int(self._samplerate * MICRO_FADE_SECONDS))
                self._zero_cross_frames = max(1, int(self._samplerate * ZERO_CROSS_WINDOW_SECONDS))

        start_frame = int(max(0.0, start_seconds) * samplerate)
        start_frame = self._snap_to_zero_crossing(sound_file, start_frame)
        try:
            sound_file.seek(start_frame)
        except Exception:  # pylint: disable=broad-except
            sound_file.seek(0)
            start_frame = 0

        resample_ratio = float(self._samplerate) / float(samplerate or 1)

        gain = 1.0
        if gain_db is not None:
            try:
                gain = math.pow(10.0, max(min(gain_db, 18.0), -60.0) / 20.0)
            except Exception:  # pylint: disable=broad-except
                gain = 1.0

        loop_frames: Optional[tuple[int, int]] = None
        if loop is not None:
            loop_start = max(0, int(loop[0] * samplerate))
            loop_end = max(loop_start + 1, int(loop[1] * samplerate))
            loop_frames = (loop_start, loop_end)

        source = MixerSource(
            source_id=source_id,
            path=Path(path),
            sound_file=sound_file,
            samplerate=samplerate,
            channels=channels,
            resample_ratio=resample_ratio,
            buffer=np.zeros((0, self._channels), dtype=np.float32),
            gain=gain,
            loop_range=loop_frames,
            fade_in_remaining=self._micro_fade_frames,
            stop_requested=False,
            on_progress=on_progress,
            on_finished=on_finished,
            position_frames=start_frame,
        )

        with self._lock:
            old = self._sources.pop(source_id, None)
            self._sources[source_id] = source
        if old:
            try:
                old.sound_file.close()
            except Exception:  # pylint: disable=broad-except
                pass
            old.finished_event.set()

        self._active_event.set()
        self._ensure_thread()
        return source.finished_event

    def set_gain_db(self, source_id: str, gain_db: Optional[float]) -> None:
        with self._lock:
            source = self._sources.get(source_id)
            if not source:
                return
            if gain_db is None:
                source.gain = 1.0
                return
            try:
                source.gain = math.pow(10.0, max(min(gain_db, 18.0), -60.0) / 20.0)
            except Exception:  # pylint: disable=broad-except
                source.gain = 1.0

    def set_loop(self, source_id: str, loop: Optional[tuple[float, float]]) -> None:
        with self._lock:
            source = self._sources.get(source_id)
            if not source:
                return
            if loop is None:
                source.loop_range = None
                return
            start, end = loop
            samplerate = source.samplerate or 1
            start_frame = max(0, int(start * samplerate))
            end_frame = max(start_frame + 1, int(end * samplerate))
            source.loop_range = (start_frame, end_frame)

    def pause_source(self, source_id: str) -> None:
        with self._lock:
            source = self._sources.get(source_id)
            if source:
                source.paused = True

    def resume_source(self, source_id: str) -> None:
        with self._lock:
            source = self._sources.get(source_id)
            if source:
                source.paused = False
                self._active_event.set()

    def fade_out_source(self, source_id: str, duration: float) -> None:
        with self._lock:
            source = self._sources.get(source_id)
            if not source:
                return
            if duration <= 0.0:
                source.fade_out_remaining = 0
                source.buffer = np.zeros((0, self._channels), dtype=np.float32)
                source.paused = False
                source.stop_requested = True
                return
            frames = max(1, int(self._samplerate * duration))
            source.fade_out_remaining = frames
            source.stop_requested = True
            self._active_event.set()

    def stop_source(self, source_id: str) -> None:
        source = self._pop_source(source_id)
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
        with self._lock:
            source = self._sources.get(source_id)
            if not source:
                return
            source.on_progress = on_progress
            source.on_finished = on_finished

    def _pop_source(self, source_id: str) -> Optional[MixerSource]:
        with self._lock:
            return self._sources.pop(source_id, None)

    def _run(self) -> None:
        try:
            with self._stream_factory(float(self._samplerate), self._channels) as stream:
                while not self._stop_event.is_set():
                    if not self._active_event.wait(timeout=0.05):
                        continue
                    block, progresses, finished_ids = self._mix_once()
                    if block is None:
                        self._active_event.clear()
                        continue
                    try:
                        stream.write(block)
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.error("Błąd zapisu do strumienia mixer: %s", exc)
                        break
                    for source_id, seconds, callback in progresses:
                        try:
                            callback(source_id, seconds)
                        except Exception as exc:  # pylint: disable=broad-except
                            logger.error("Błąd callbacku postępu mixer: %s", exc)
                    for source_id in finished_ids:
                        self._finalize_source(source_id)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Błąd wątku DeviceMixer: %s", exc)
        finally:
            self._active_event.clear()

    def _mix_once(self):
        with self._lock:
            sources = list(self._sources.values())
        if not sources:
            return None, [], []

        block = np.zeros((self._block_size, self._channels), dtype=np.float32)
        progresses: list[tuple[str, float, Callable[[str, float], None]]] = []
        finished_ids: list[str] = []

        for source in sources:
            data, frames_out, finished = self._render_source(source)
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

    def _render_source(self, source: MixerSource) -> tuple[np.ndarray, int, bool]:
        output = np.zeros((self._block_size, self._channels), dtype=np.float32)
        finished = False
        frames_out = 0

        if source.paused:
            return output, frames_out, finished

        if source.stop_requested and source.fade_out_remaining == 0:
            return output, frames_out, True

        buffer = source.buffer

        target_block = self._block_size
        if source.stop_requested and source.fade_out_remaining > 0:
            target_block = min(target_block, source.fade_out_remaining)

        while len(buffer) < target_block:
            remaining = target_block - len(buffer)
            need_src = max(1, int(math.ceil(remaining / max(source.resample_ratio, 1e-6))))
            try:
                data = source.sound_file.read(need_src, dtype="float32", always_2d=True)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Błąd odczytu pliku %s: %s", source.path, exc)
                finished = True
                break

            frames_read = len(data)
            if frames_read == 0:
                finished = True
                break

            loop_range = source.loop_range
            if loop_range and source.position_frames + frames_read >= loop_range[1]:
                frames_allowed = loop_range[1] - source.position_frames
                frames_allowed = max(0, frames_allowed)
                if frames_allowed < frames_read:
                    data = data[:frames_allowed]
                    frames_read = frames_allowed
                try:
                    source.sound_file.seek(loop_range[0])
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Błąd ustawienia pętli: %s", exc)
                    source.loop_range = None
                else:
                    source.pending_fade_in = max(source.pending_fade_in, self._micro_fade_frames)
                source.position_frames = loop_range[0]
            else:
                source.position_frames += frames_read

            data = self._match_channels(data, self._channels)
            if abs(source.resample_ratio - 1.0) > 1e-6:
                target_frames = max(1, int(round(frames_read * source.resample_ratio)))
                data = _resample_to_length(data, target_frames)

            if len(buffer) == 0:
                buffer = data
            else:
                buffer = np.concatenate([buffer, data], axis=0)

        if len(buffer) >= self._block_size:
            output = buffer[: self._block_size]
            buffer = buffer[self._block_size :]
            frames_out = len(output)
        else:
            frames_out = len(buffer)
            if frames_out:
                output[:frames_out] = buffer
            finished = True
            buffer = np.zeros((0, self._channels), dtype=np.float32)

        output = self._apply_fades(source, output, frames_out)
        if source.stop_requested and source.fade_out_remaining == 0:
            finished = True
            source.buffer = np.zeros((0, self._channels), dtype=np.float32)
        output = output * float(source.gain)
        source.buffer = buffer
        return output, frames_out, finished

    def _apply_fades(self, source: MixerSource, data: np.ndarray, frames_out: int) -> np.ndarray:
        if frames_out == 0:
            return data
        result = data

        if source.pending_fade_in > 0:
            frames = min(frames_out, source.pending_fade_in)
            fade = np.linspace(0.0, 1.0, frames, endpoint=False, dtype=result.dtype)
            result = result.copy()
            result[:frames] *= fade[:, None]
            source.pending_fade_in = max(0, source.pending_fade_in - frames)

        if source.fade_in_remaining > 0:
            frames = min(frames_out, source.fade_in_remaining)
            fade = np.linspace(0.0, 1.0, frames, endpoint=False, dtype=result.dtype)
            result = result.copy()
            result[:frames] *= fade[:, None]
            source.fade_in_remaining = max(0, source.fade_in_remaining - frames)

        if source.fade_out_remaining > 0:
            frames = min(frames_out, source.fade_out_remaining)
            fade = np.linspace(1.0, 0.0, frames, endpoint=False, dtype=result.dtype)
            result = result.copy()
            result[-frames:] *= fade[:, None]
            source.fade_out_remaining = max(0, source.fade_out_remaining - frames)
            if source.fade_out_remaining == 0:
                source.buffer = np.zeros((0, self._channels), dtype=np.float32)
        return result

    def _finalize_source(self, source_id: str) -> None:
        source = self._pop_source(source_id)
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
        if not self._sources:
            self._active_event.clear()

    def _snap_to_zero_crossing(self, sound_file, target_frame: int) -> int:
        if target_frame <= 0 or self._zero_cross_frames <= 0:
            return max(0, target_frame)
        window = self._zero_cross_frames
        start = max(0, target_frame - window)
        try:
            sound_file.seek(start)
            data = sound_file.read(window * 2, dtype="float32", always_2d=True)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Nie udało się pobrać okna zero-crossing: %s", exc)
            return max(0, target_frame)
        if data.size == 0:
            return max(0, target_frame)
        values = data[:, 0]
        crossings = [
            idx for idx in range(1, len(values)) if values[idx - 1] == 0 or values[idx - 1] * values[idx] <= 0
        ]
        if not crossings:
            return max(0, target_frame)
        desired = target_frame - start
        idx = min(crossings, key=lambda i: abs(i - desired))
        return start + idx

    def _match_channels(self, data, channels: int):
        if data.shape[1] == channels:
            return data
        if data.shape[1] > channels:
            return data[:, :channels]
        pad_count = channels - data.shape[1]
        pad = np.repeat(data[:, -1:], pad_count, axis=1)
        return np.concatenate([data, pad], axis=1)

