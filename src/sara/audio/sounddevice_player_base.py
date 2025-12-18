"""Sounddevice player implementation."""

from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from typing import Callable, Dict, Optional

from sara.audio.resampling import _resample_to_length
from sara.audio.transcoding import open_audio_file_with_transcoding
from sara.audio.types import AudioDevice

logger = logging.getLogger(__name__)

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover - środowiska bez sounddevice
    sd = None

try:
    import soundfile as sf
except ImportError:  # pragma: no cover - środowiska bez soundfile
    sf = None

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy instalowane z soundfile
    np = None


class SoundDevicePlayer:
    """Player odtwarzający audio przy użyciu sounddevice + soundfile."""

    def __init__(self, device: AudioDevice, stream_kwargs: Optional[dict] = None):
        if sd is None:
            raise RuntimeError("sounddevice niedostępne")
        if sf is None:
            raise RuntimeError("soundfile niedostępne")
        if device.raw_index is None:
            raise RuntimeError("Brak indeksu urządzenia sounddevice")
        self.device = device
        self._stream_kwargs = stream_kwargs or {}
        self._thread: Optional[Thread] = None
        self._stop_event: Optional[Event] = None
        self._pause_event: Optional[Event] = None
        self._current_item: Optional[str] = None
        self._finished_event: Optional[Event] = None
        self._lock = Lock()
        self._position = 0
        self._path: Optional[Path] = None
        self._on_finished: Optional[Callable[[str], None]] = None
        self._on_progress: Optional[Callable[[str, float], None]] = None
        self._samplerate: int = 0
        self._total_frames: int = 0
        self._gain_factor: float = 1.0
        self._loop_request: Optional[tuple[float, float]] = None
        self._loop_active: bool = False
        self._loop_start_frame: int = 0
        self._loop_end_frame: int = 0
        self._fade_thread: Optional[Thread] = None
        self._fade_stop_event: Optional[Event] = None
        self._transcoded_path: Optional[Path] = None
        self._pending_fade_in: int = 0

    def play(
        self,
        playlist_item_id: str,
        source_path: str,
        *,
        start_seconds: float = 0.0,
        allow_loop: bool = True,
        mix_trigger_seconds: float | None = None,
        on_mix_trigger: Callable[[], None] | None = None,
    ) -> Event:  # noqa: D401
        path = Path(source_path)
        with self._lock:
            if self._current_item == playlist_item_id:
                return self._finished_event or Event()
            self.stop()
            self._current_item = playlist_item_id
            self._path = path
            try:
                sound_file = self._open_audio_file(path)
            except Exception as exc:  # pylint: disable=broad-except
                self._current_item = None
                raise RuntimeError(f"Nie udało się otworzyć pliku audio: {exc}") from exc

            samplerate = sound_file.samplerate
            channels = sound_file.channels
            stream_kwargs = dict(self._stream_kwargs)
            output_samplerate = float(samplerate)
            resample_ratio = 1.0
            resample_state = {"src_pos": 0.0, "dst_pos": 0.0}
            device_info: Dict[str, object] = {}
            if sd is not None and self.device.raw_index is not None:
                try:
                    device_info = sd.query_devices(self.device.raw_index)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.debug("Nie udało się pobrać informacji o urządzeniu: %s", exc)
                    device_info = {}
                try:
                    host_index_raw = device_info.get("hostapi")
                    host_index = int(host_index_raw) if host_index_raw is not None else -1
                except Exception:  # pylint: disable=broad-except
                    host_index = -1
                if host_index >= 0:
                    try:
                        host_name = sd.query_hostapis()[host_index]["name"].lower()
                        if "wasapi" in host_name and "extra_settings" not in stream_kwargs:
                            stream_kwargs["extra_settings"] = sd.WasapiSettings(exclusive=False)
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.debug("Nie udało się skonfigurować ustawień WASAPI: %s", exc)

                try:
                    sd.check_output_settings(
                        device=self.device.raw_index,
                        samplerate=output_samplerate,
                        channels=channels,
                    )
                except Exception:
                    fallback_rate: Optional[float] = None
                    try:
                        fallback_raw = device_info.get("default_samplerate")
                        if fallback_raw:
                            fallback_rate = float(fallback_raw)
                    except Exception:  # pylint: disable=broad-except
                        fallback_rate = None
                    if fallback_rate and samplerate and fallback_rate != samplerate:
                        output_samplerate = fallback_rate
                        resample_ratio = output_samplerate / float(samplerate)
                        try:
                            sd.check_output_settings(
                                device=self.device.raw_index,
                                samplerate=output_samplerate,
                                channels=channels,
                            )
                        except Exception as exc:  # pylint: disable=broad-except
                            raise RuntimeError(
                                "Urządzenie PFL nie obsługuje wymaganej częstotliwości próbkowania"
                            ) from exc
                    else:
                        raise RuntimeError("Urządzenie PFL nie obsługuje częstotliwości próbkowania pliku")
            self._stop_event = Event()
            self._pause_event = Event()
            self._finished_event = Event()
            stop_event = self._stop_event
            self._current_item = playlist_item_id
            self._path = path
            self._samplerate = samplerate
            self._total_frames = len(sound_file)

            start_frame = int(max(0.0, start_seconds) * samplerate)
            if start_frame >= self._total_frames and self._total_frames > 0:
                start_frame = max(self._total_frames - 1, 0)
            self._position = start_frame

            if self._position:
                try:
                    sound_file.seek(self._position)
                except Exception:
                    self._position = 0
                    sound_file.seek(0)

            self._apply_loop_request(samplerate)

            def _run() -> None:
                with sound_file:
                    restart_attempted = False
                    while True:
                        try:
                            with sd.OutputStream(
                                device=self.device.raw_index,
                                samplerate=output_samplerate,
                                channels=channels,
                                dtype="float32",
                                **stream_kwargs,
                            ) as stream:
                                block = 4096
                                while stop_event is not None and not stop_event.is_set():
                                    if self._pause_event.is_set():
                                        time.sleep(0.05)
                                        continue
                                    data = sound_file.read(block, dtype="float32", always_2d=True)
                                    frames_read = len(data)
                                    if data.size == 0:
                                        with self._lock:
                                            loop_active = self._loop_active
                                            loop_start_frame = self._loop_start_frame
                                            loop_end_frame = self._loop_end_frame
                                        if loop_active and loop_end_frame > loop_start_frame:
                                            sound_file.seek(loop_start_frame)
                                            self._position = loop_start_frame
                                            continue
                                        break
                                    with self._lock:
                                        gain_factor = self._gain_factor
                                        loop_active = self._loop_active
                                        loop_start_frame = self._loop_start_frame
                                        loop_end_frame = self._loop_end_frame
                                    output_block = data
                                    if gain_factor != 1.0:
                                        output_block = output_block * gain_factor
                                    if frames_read and abs(resample_ratio - 1.0) > 1e-6:
                                        resample_state["src_pos"] += frames_read
                                        expected_total = resample_state["src_pos"] * resample_ratio
                                        target_frames = int(round(expected_total - resample_state["dst_pos"]))
                                        target_frames = max(1, target_frames)
                                        output_block = _resample_to_length(output_block, target_frames)
                                        resample_state["dst_pos"] += len(output_block)
                                    if np is not None and self._pending_fade_in > 0 and len(output_block):
                                        frames = min(len(output_block), self._pending_fade_in)
                                        fade = np.linspace(0.0, 1.0, frames, endpoint=False, dtype=output_block.dtype)
                                        output_block = output_block.copy()
                                        output_block[:frames] *= fade[:, None]
                                        self._pending_fade_in = max(0, self._pending_fade_in - frames)
                                    will_loop = (
                                        loop_active
                                        and loop_end_frame > loop_start_frame
                                        and self._position + frames_read >= loop_end_frame
                                    )
                                    if will_loop and np is not None and len(output_block):
                                        fade_frames = min(len(output_block), max(1, int(output_samplerate * 0.003)))
                                        fade = np.linspace(1.0, 0.0, fade_frames, endpoint=False, dtype=output_block.dtype)
                                        output_block = output_block.copy()
                                        output_block[-fade_frames:] *= fade[:, None]
                                        self._pending_fade_in = fade_frames
                                    stream.write(output_block)
                                    self._position += frames_read
                                    if (
                                        loop_active
                                        and loop_end_frame > loop_start_frame
                                        and self._position >= loop_end_frame
                                    ):
                                        try:
                                            sound_file.seek(loop_start_frame)
                                        except Exception as exc:  # pylint: disable=broad-except
                                            logger.error("Błąd ustawienia pętli: %s", exc)
                                            with self._lock:
                                                self._loop_active = False
                                        else:
                                            self._position = loop_start_frame
                                            continue
                                    if self._on_progress:
                                        seconds = self._position / self._samplerate if self._samplerate else 0.0
                                        try:
                                            self._on_progress(self._current_item or playlist_item_id, seconds)
                                        except Exception as exc:  # pylint: disable=broad-except
                                            logger.error("Błąd callbacku postępu: %s", exc)
                            break
                        except Exception as exc:  # pylint: disable=broad-except
                            should_retry = False
                            status_code = getattr(exc, "errno", None) or getattr(exc, "status", None)
                            if (
                                sd is not None
                                and isinstance(exc, Exception)
                                and status_code == -9983
                                and not restart_attempted
                                and stop_event is not None
                                and not stop_event.is_set()
                            ):
                                restart_attempted = True
                                should_retry = True
                                logger.warning(
                                    "Strumień sounddevice zatrzymany (PaError -9983) na %s, ponawiam...",
                                    self.device.name,
                                )
                                time.sleep(0.05)
                            if not should_retry:
                                logger.error("Błąd odtwarzania sounddevice: %s", exc)
                                break
                        if not restart_attempted:
                            break
                    should_notify = not stop_event.is_set() if stop_event else True
                    current_item = self._current_item
                    self._position = 0
                    if self._finished_event:
                        self._finished_event.set()
                    self._current_item = None
                    if self._on_progress and current_item:
                        try:
                            total = self._total_frames / self._samplerate if self._samplerate else 0.0
                            self._on_progress(current_item, total)
                        except Exception as exc:  # pylint: disable=broad-except
                            logger.error("Błąd callbacku postępu: %s", exc)
                    if should_notify and current_item and self._on_finished:
                        try:
                            self._on_finished(current_item)
                        except Exception as exc:  # pylint: disable=broad-except
                            logger.error("Błąd callbacku zakończenia odtwarzania: %s", exc)
                    self._cleanup_transcoded_file()

            self._thread = Thread(target=_run, daemon=True)
            self._thread.start()
            return self._finished_event

    def pause(self) -> None:  # noqa: D401
        with self._lock:
            if self._pause_event and not self._pause_event.is_set():
                self._pause_event.set()

    def stop(self) -> None:  # noqa: D401
        fade_thread: Optional[Thread]
        fade_stop: Optional[Event]
        with self._lock:
            fade_thread = self._fade_thread
            fade_stop = self._fade_stop_event
            self._fade_thread = None
            self._fade_stop_event = None
            if fade_stop:
                fade_stop.set()
            self._stop_locked()

        if fade_thread and fade_thread.is_alive() and fade_thread is not current_thread():
            fade_thread.join(timeout=1.5)

    def fade_out(self, duration: float) -> None:  # noqa: D401
        if duration <= 0.0:
            self.stop()
            return

        with self._lock:
            existing_thread = self._fade_thread
            existing_stop_event = self._fade_stop_event

        if existing_stop_event:
            existing_stop_event.set()
        if existing_thread and existing_thread.is_alive() and existing_thread is not current_thread():
            existing_thread.join(timeout=1.5)

        with self._lock:
            if (
                self._current_item is None
                or self._stop_event is None
                or self._stop_event.is_set()
            ):
                should_stop = True
            else:
                should_stop = False
                initial_gain = self._gain_factor
                target_item = self._current_item
                fade_stop_event = Event()
                self._fade_stop_event = fade_stop_event

                def _runner() -> None:
                    interrupted = False
                    try:
                        steps = max(4, int(duration / 0.05))
                        sleep_slice = duration / steps if steps else duration
                        for index in range(steps):
                            if fade_stop_event.is_set():
                                break
                            with self._lock:
                                if target_item is not None and self._current_item != target_item:
                                    interrupted = True
                                    break
                            fraction = 1.0 - float(index + 1) / steps
                            with self._lock:
                                self._gain_factor = max(0.0, initial_gain * fraction)
                            time.sleep(sleep_slice)
                    finally:
                        with self._lock:
                            same_item = target_item is not None and self._current_item == target_item
                        if not fade_stop_event.is_set():
                            fade_stop_event.set()
                        if same_item and not interrupted:
                            self.stop()

                thread = Thread(target=_runner, daemon=True)
                self._fade_thread = thread

        if should_stop:
            self.stop()
            return

        assert self._fade_thread is not None  # mypy
        self._fade_thread.start()

    def _stop_locked(self) -> None:
        item_id = self._current_item
        if self._stop_event and not self._stop_event.is_set():
            self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None
        self._stop_event = None
        self._pause_event = None
        if self._finished_event and not self._finished_event.is_set():
            self._finished_event.set()
        self._finished_event = None
        self._current_item = None
        self._position = 0
        self._path = None
        self._samplerate = 0
        self._total_frames = 0
        self._loop_request = None
        self._loop_active = False
        self._loop_start_frame = 0
        self._loop_end_frame = 0
        self._pending_fade_in = 0
        if self._on_progress and item_id:
            try:
                self._on_progress(item_id, 0.0)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Błąd callbacku postępu: %s", exc)
        self._cleanup_transcoded_file()

    def _open_audio_file(self, path: Path):
        if sf is None:
            raise RuntimeError("soundfile niedostępne")
        self._cleanup_transcoded_file()
        sound_file, transcoded_path = open_audio_file_with_transcoding(path, sf=sf)
        if transcoded_path is not None:
            self._transcoded_path = transcoded_path
        return sound_file

    def _cleanup_transcoded_file(self) -> None:
        if self._transcoded_path:
            try:
                self._transcoded_path.unlink(missing_ok=True)
            except Exception:
                pass
            self._transcoded_path = None

    def set_finished_callback(self, callback: Optional[Callable[[str], None]]) -> None:  # noqa: D401
        with self._lock:
            self._on_finished = callback

    def set_progress_callback(self, callback: Optional[Callable[[str, float], None]]) -> None:  # noqa: D401
        with self._lock:
            self._on_progress = callback

    def set_mix_trigger(
        self,
        mix_trigger_seconds: Optional[float],
        on_mix_trigger: Optional[Callable[[], None]],
    ) -> None:
        # sounddevice backend nie obsługuje natywnego triggera miksu; metoda dla kompatybilności.
        return

    def set_gain_db(self, gain_db: Optional[float]) -> None:  # noqa: D401
        with self._lock:
            if gain_db is None:
                self._gain_factor = 1.0
            else:
                try:
                    gain = max(min(gain_db, 18.0), -60.0)
                    self._gain_factor = math.pow(10.0, gain / 20.0)
                except Exception:
                    self._gain_factor = 1.0

    def set_loop(self, start_seconds: Optional[float], end_seconds: Optional[float]) -> None:  # noqa: D401
        with self._lock:
            if (
                start_seconds is None
                or end_seconds is None
                or end_seconds <= start_seconds
            ):
                self._loop_request = None
                self._loop_active = False
                self._loop_start_frame = 0
                self._loop_end_frame = 0
                return
            self._loop_request = (max(0.0, start_seconds), end_seconds)
            if self._samplerate:
                self._apply_loop_request(self._samplerate)

    def _apply_loop_request(self, samplerate: int) -> None:
        if not self._loop_request:
            self._loop_active = False
            self._loop_start_frame = 0
            self._loop_end_frame = 0
            return
        start_seconds, end_seconds = self._loop_request
        start_frame = int(start_seconds * samplerate)
        end_frame = int(end_seconds * samplerate)
        if self._total_frames:
            max_frame = self._total_frames - 1
            start_frame = max(0, min(start_frame, max_frame))
            end_frame = max(start_frame + 1, min(end_frame, self._total_frames))
        if end_frame <= start_frame:
            self._loop_active = False
            return
        self._loop_start_frame = start_frame
        self._loop_end_frame = end_frame
        self._loop_active = True

    def supports_mix_trigger(self) -> bool:
        return False
