"""Warstwa abstrakcji urządzeń audio (WASAPI/ASIO)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
import math
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from threading import Event, Lock, Thread, Timer, current_thread
from typing import Callable, Dict, List, Optional, Protocol
import warnings

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

try:
    from pycaw.pycaw import AudioUtilities
except ImportError:  # pragma: no cover - środowiska bez pycaw
    AudioUtilities = None
else:  # pragma: no cover - tylko gdy pycaw obecny
    warnings.filterwarnings(
        "ignore",
        message="COMError attempting to get property",
        category=UserWarning,
        module="pycaw.utils",
    )

try:
    import clr  # type: ignore
except ImportError:  # pragma: no cover - pythonnet opcjonalny
    clr = None

try:
    from sara.audio.bass import BassBackend
except Exception:  # pragma: no cover - BASS opcjonalny
    BassBackend = None


class BackendType(Enum):
    WASAPI = "wasapi"
    ASIO = "asio"
    BASS = "bass"


@dataclass
class AudioDevice:
    id: str
    name: str
    backend: BackendType
    raw_index: Optional[int] = None
    is_default: bool = False


class Player(Protocol):
    def play(self, playlist_item_id: str, source_path: str, *, start_seconds: float = 0.0) -> Optional[Event]: ...

    def pause(self) -> None: ...

    def stop(self) -> None: ...

    def fade_out(self, duration: float) -> None: ...

    def set_finished_callback(self, callback: Optional[Callable[[str], None]]) -> None: ...

    def set_progress_callback(self, callback: Optional[Callable[[str, float], None]]) -> None: ...

    def set_gain_db(self, gain_db: Optional[float]) -> None: ...

    def set_loop(self, start_seconds: Optional[float], end_seconds: Optional[float]) -> None: ...

    def set_gain_db(self, gain_db: Optional[float]) -> None: ...


class BackendProvider(Protocol):
    backend: BackendType

    def list_devices(self) -> List[AudioDevice]: ...

    def create_player(self, device: AudioDevice) -> Player: ...


def _match_sounddevice_device(target_name: str, host_keywords: tuple[str, ...]) -> Optional[int]:
    if sd is None:
        return None
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Nie udało się pobrać listy urządzeń sounddevice: %s", exc)
        return None

    target_lower = target_name.lower()
    exact_matches: list[tuple[int, int]] = []
    partial_matches: list[tuple[int, int]] = []

    for index, info in enumerate(devices):
        host_name = hostapis[info["hostapi"]]["name"]
        keyword_index = next(
            (i for i, keyword in enumerate(host_keywords) if keyword.lower() in host_name.lower()),
            None,
        )
        if keyword_index is None:
            continue
        if info.get("max_output_channels", 0) <= 0:
            continue
        name_lower = info["name"].lower()
        entry = (keyword_index, index)
        if name_lower == target_lower:
            exact_matches.append(entry)
        elif target_lower in name_lower:
            partial_matches.append(entry)

    if exact_matches:
        _, chosen = min(exact_matches, key=lambda pair: (pair[0], pair[1]))
        return chosen
    if partial_matches:
        _, chosen = min(partial_matches, key=lambda pair: (pair[0], pair[1]))
        return chosen
    return None


def _resample_to_length(block, target_frames: int):
    if np is None or target_frames <= 0:
        return block
    src_frames = block.shape[0]
    if src_frames == 0 or src_frames == target_frames:
        return block
    if src_frames == 1:
        return np.repeat(block, target_frames, axis=0).astype(block.dtype, copy=False)
    src_idx = np.arange(src_frames, dtype=np.float64)
    target_idx = np.linspace(0.0, src_frames - 1, target_frames, dtype=np.float64)
    resampled = np.empty((target_frames, block.shape[1]), dtype=np.float32)
    for channel in range(block.shape[1]):
        resampled[:, channel] = np.interp(target_idx, src_idx, block[:, channel])
    return resampled.astype(block.dtype, copy=False)


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

    def play(self, playlist_item_id: str, source_path: str, *, start_seconds: float = 0.0) -> Optional[Event]:  # noqa: D401
        self.stop()
        self._current_item = playlist_item_id
        logger.info("[MOCK] Odtwarzanie %s na %s (%s)", source_path, self.device.name, playlist_item_id)
        self._progress_seconds = max(0.0, start_seconds)
        self._timer = Timer(0.1, self._tick)
        self._timer.start()
        return None

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

    def set_gain_db(self, gain_db: Optional[float]) -> None:  # noqa: D401
        self._gain_db = gain_db

    def set_loop(self, start_seconds: Optional[float], end_seconds: Optional[float]) -> None:  # noqa: D401
        if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
            self._loop_end = None
            self._loop_start = 0.0
            return
        self._loop_start = max(0.0, start_seconds)
        self._loop_end = end_seconds

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


_TRANSCODE_EXTENSIONS = {".mp4", ".m4a", ".m4v"}


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

    def play(self, playlist_item_id: str, source_path: str, *, start_seconds: float = 0.0) -> Event:  # noqa: D401
        path = Path(source_path)
        with self._lock:
            if self._current_item == playlist_item_id and self._pause_event and self._pause_event.is_set():
                self._pause_event.clear()
                return self._finished_event or Event()

            self._stop_locked()

            try:
                sound_file = self._open_audio_file(path)
            except Exception as exc:  # pylint: disable=broad-except
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
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.error("Błąd odtwarzania sounddevice: %s", exc)
                    finally:
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
        self._cleanup_transcoded_file()

    def _open_audio_file(self, path: Path):
        if sf is None:
            raise RuntimeError("soundfile niedostępne")
        self._cleanup_transcoded_file()
        try:
            return sf.SoundFile(path, mode="r")
        except Exception:
            if path.suffix.lower() not in _TRANSCODE_EXTENSIONS:
                raise
            wav_path = self._transcode_source(path)
            try:
                sound_file = sf.SoundFile(wav_path, mode="r")
            except Exception as exc:  # pylint: disable=broad-except
                try:
                    wav_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise RuntimeError("Nie udało się odczytać przekodowanego pliku MP4") from exc
            self._transcoded_path = wav_path
            return sound_file

    def _transcode_source(self, source: Path) -> Path:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("FFmpeg jest wymagany do odtwarzania plików MP4/M4A")
        fd, temp_name = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        target = Path(temp_name)
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(target),
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError as exc:  # pragma: no cover - zależy od środowiska
            target.unlink(missing_ok=True)
            raise RuntimeError("FFmpeg nie został znaleziony w PATH") from exc
        except subprocess.CalledProcessError as exc:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg nie mógł zdekodować pliku {source.name}") from exc
        return target

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


class WasapiPlayer(SoundDevicePlayer):
    """Player wykorzystujący urządzenie WASAPI poprzez sounddevice."""

    def __init__(self, device: AudioDevice):
        if device.raw_index is None:
            raw_index = _match_sounddevice_device(device.name, ("WASAPI", "MME"))
            if raw_index is None:
                raise RuntimeError("Nie znaleziono odpowiednika WASAPI w sounddevice")
            device.raw_index = raw_index
        super().__init__(device, stream_kwargs={"blocksize": 512, "latency": "low"})


class AsioPlayer(SoundDevicePlayer):
    """Player wykorzystujący sterownik ASIO (przez sounddevice)."""

    def __init__(self, device: AudioDevice):
        if device.raw_index is None:
            raw_index = _match_sounddevice_device(device.name, ("ASIO",))
            if raw_index is None:
                raise RuntimeError("Nie znaleziono odpowiednika ASIO w sounddevice")
            device.raw_index = raw_index
        super().__init__(device, stream_kwargs={"blocksize": 256, "latency": "low"})


class SoundDeviceBackend:
    """Backend oparty na bibliotece sounddevice (PortAudio)."""

    def __init__(self, backend: BackendType, keywords: tuple[str, ...]):
        self.backend = backend
        self._keywords = keywords

    def list_devices(self) -> List[AudioDevice]:
        if sd is None:
            logger.warning("sounddevice nie jest dostępne - brak urządzeń %s", self.backend.value)
            return []

        devices: List[AudioDevice] = []
        default_output = None
        try:
            default_setting = sd.default.device
            if isinstance(default_setting, (list, tuple)) and len(default_setting) > 1:
                default_output = default_setting[1]
        except Exception:  # pragma: no cover - konfiguracje bez domyślnego urządzenia
            default_output = None

        try:
            hostapis = sd.query_hostapis()
            for index, info in enumerate(sd.query_devices()):
                host_name = hostapis[info["hostapi"]]["name"]
                if not any(keyword.lower() in host_name.lower() for keyword in self._keywords):
                    continue
                if info.get("max_output_channels", 0) <= 0:
                    continue
                device_id = f"{self.backend.value}:{index}"
                devices.append(
                    AudioDevice(
                        id=device_id,
                        name=info["name"],
                        backend=self.backend,
                        raw_index=index,
                        is_default=default_output == index,
                    )
                )
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Nie udało się pobrać urządzeń %s: %s", self.backend.value, exc)
        return devices

    def create_player(self, device: AudioDevice) -> Player:
        try:
            stream_kwargs = {"blocksize": 1024, "latency": "low"}
            return SoundDevicePlayer(device, stream_kwargs=stream_kwargs)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Nie udało się stworzyć SoundDevicePlayer dla %s: %s", device.name, exc)
            return MockPlayer(device)


class PycawBackend:
    """Szkic backendu WASAPI opartego o pycaw."""

    backend = BackendType.WASAPI

    def list_devices(self) -> List[AudioDevice]:
        if AudioUtilities is None:
            logger.debug("pycaw niedostępny - pomijam enumerację WASAPI")
            return []

        devices: List[AudioDevice] = []
        try:
            all_devices = AudioUtilities.GetAllDevices()
            default_device = AudioUtilities.GetSpeakers()
            default_id = getattr(default_device, "id", None)
            for endpoint in all_devices:
                try:
                    state = getattr(endpoint, "State", None)
                    if state not in (0, 1):
                        continue
                    friendly_name = getattr(endpoint, "FriendlyName", "Unknown")
                    endpoint_id = getattr(endpoint, "id", None) or getattr(endpoint, "Id", None)
                    if not endpoint_id:
                        continue
                    devices.append(
                        AudioDevice(
                            id=f"{self.backend.value}:{endpoint_id}",
                            name=str(friendly_name),
                            backend=self.backend,
                            raw_index=None,
                            is_default=endpoint_id == default_id,
                        )
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    logger.debug("Pominięto urządzenie WASAPI: %s", exc)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Enumeracja WASAPI przez pycaw nie powiodła się: %s", exc)
        return devices

    def create_player(self, device: AudioDevice) -> Player:
        try:
            return WasapiPlayer(device)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Nie udało się stworzyć playera WASAPI dla %s: %s", device.name, exc)
            return MockPlayer(device)


class AsioBackend:
    """Szkic backendu ASIO z użyciem pythonnet."""

    backend = BackendType.ASIO

    def __init__(self) -> None:
        if clr is not None:
            try:
                clr.AddReference("NAudio")  # pragma: no cover - zależne od środowiska
            except Exception:  # pylint: disable=broad-except
                logger.debug("Biblioteka NAudio nie została załadowana")

    def list_devices(self) -> List[AudioDevice]:
        # TODO: wykorzystać NAudio/ASIO do enumeracji sterowników
        logger.debug("Enumeracja sterowników ASIO wymaga implementacji pythonnet")
        return []

    def create_player(self, device: AudioDevice) -> Player:
        try:
            return AsioPlayer(device)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Nie udało się stworzyć playera ASIO dla %s: %s", device.name, exc)
            return MockPlayer(device)


class AudioEngine:
    """Zarządza wyborem urządzeń i instancjami playerów."""

    def __init__(self) -> None:
        self._providers: List[BackendProvider] = []
        if BassBackend is not None:
            bass_backend = BassBackend()
            if getattr(bass_backend, "is_available", False):
                bass_backend.backend = BackendType.BASS
                self._providers.append(bass_backend)
        self._providers.extend(
            [
                SoundDeviceBackend(BackendType.WASAPI, ("WASAPI",)),
                SoundDeviceBackend(BackendType.ASIO, ("ASIO",)),
                PycawBackend(),
                AsioBackend(),
            ]
        )
        self._devices: Dict[str, AudioDevice] = {}
        self._players: Dict[str, Player] = {}

    def refresh_devices(self) -> None:
        self._devices.clear()
        for provider in self._providers:
            for device in provider.list_devices():
                label = f"{provider.backend.name.lower()}: {device.name}"
                device_labelled = AudioDevice(
                    id=device.id,
                    name=label,
                    backend=device.backend,
                    raw_index=device.raw_index,
                    is_default=device.is_default,
                )
                self._devices[device.id] = device_labelled
        logger.debug("Zarejestrowano %d urządzeń audio", len(self._devices))

    def get_devices(self) -> List[AudioDevice]:
        if not self._devices:
            self.refresh_devices()
        return list(self._devices.values())

    def create_player(self, device_id: str) -> Player:
        if device_id in self._players:
            return self._players[device_id]

        device = self._devices.get(device_id)
        if device is None:
            raise ValueError(f"Nieznane urządzenie: {device_id}")

        provider = self._get_provider(device.backend)
        player = provider.create_player(device)
        self._players[device_id] = player
        return player

    def _get_provider(self, backend: BackendType) -> BackendProvider:
        for provider in self._providers:
            if provider.backend is backend:
                return provider
        raise ValueError(f"Brak providera dla backendu {backend}")

    def stop_all(self) -> None:
        for player in self._players.values():
            try:
                player.stop()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Nie udało się zatrzymać playera: %s", exc)
            for clear in (player.set_finished_callback, player.set_progress_callback):
                try:
                    clear(None)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.debug("Nie udało się wyczyścić callbacku playera: %s", exc)
