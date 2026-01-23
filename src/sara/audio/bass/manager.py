"""BASS manager (device lifecycle, stream helpers)."""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from sara.audio.transcoding import TRANSCODE_EXTENSIONS, transcode_source_to_wav

from ._manager import asio as _asio_ops
from ._manager import devices as _devices_ops
from ._manager import streams as _streams_ops
from ._manager.contexts import _AsioDeviceContext, _DeviceContext
from .native import BassNotAvailable, _BassLibrary

logger = logging.getLogger(__name__)


class BassManager:
    """Singleton zarządzający dostępem do BASS."""

    _instance_lock = threading.Lock()
    _instance: Optional["BassManager"] = None

    list_asio_devices = _asio_ops.list_asio_devices
    acquire_asio_device = _asio_ops.acquire_asio_device
    _release_asio_device = _asio_ops._release_asio_device
    asio_set_device = _asio_ops.asio_set_device
    asio_channel_reset = _asio_ops.asio_channel_reset
    asio_channel_enable_bass = _asio_ops.asio_channel_enable_bass
    asio_channel_join = _asio_ops.asio_channel_join
    asio_channel_set_volume = _asio_ops.asio_channel_set_volume
    asio_channel_set_rate = _asio_ops.asio_channel_set_rate
    asio_start = _asio_ops.asio_start
    asio_stop = _asio_ops.asio_stop
    asio_is_started = _asio_ops.asio_is_started
    asio_is_active = _asio_ops.asio_is_active
    asio_set_volume = _asio_ops.asio_set_volume
    asio_play_stream = _asio_ops.asio_play_stream

    acquire_device = _devices_ops.acquire_device
    _release_device = _devices_ops._release_device
    list_devices = _devices_ops.list_devices

    channel_play = _streams_ops.channel_play
    channel_pause = _streams_ops.channel_pause
    channel_stop = _streams_ops.channel_stop
    channel_set_position = _streams_ops.channel_set_position
    channel_get_seconds = _streams_ops.channel_get_seconds
    channel_is_active = _streams_ops.channel_is_active
    channel_get_length_seconds = _streams_ops.channel_get_length_seconds
    channel_set_volume = _streams_ops.channel_set_volume
    channel_slide_volume = _streams_ops.channel_slide_volume
    seconds_to_bytes = _streams_ops.seconds_to_bytes
    channel_set_position_bytes = _streams_ops.channel_set_position_bytes
    make_sync_proc = _streams_ops.make_sync_proc
    channel_set_sync_pos = _streams_ops.channel_set_sync_pos
    channel_remove_sync = _streams_ops.channel_remove_sync
    channel_set_sync_end = _streams_ops.channel_set_sync_end

    def __init__(self) -> None:
        lib_wrapper = _BassLibrary()
        self._lib = lib_wrapper.handle
        self._sync_type = lib_wrapper.sync_proc_type
        self._stream_create_file = getattr(self._lib, "BASS_StreamCreateFile", None)
        self._stream_uses_wchar = sys.platform.startswith("win")
        self._devices: dict[int, dict[str, Any]] = {}
        self._global_lock = threading.Lock()
        self._transcoded_streams: dict[int, Path] = {}
        # Zmniejsz bufor wyjściowy – duże wartości powodują „poczucie laga” oraz rozjazdy
        # między pozycją z `ChannelGetPosition` a wyzwalaczami typu SYNC_MIXTIME.
        buffer_ms_raw = os.environ.get("SARA_BASS_BUFFER_MS", "250")
        try:
            buffer_ms = int(float(buffer_ms_raw))
        except Exception:  # pragma: no cover - defensywne
            buffer_ms = 0
        if buffer_ms > 0:
            try:
                self._lib.BASS_SetConfig(0x10400, buffer_ms)  # BASS_CONFIG_BUFFER
            except Exception:  # pragma: no cover - zależne od środowiska
                pass
        # skróć opóźnienie aktualizacji, żeby pętle reagowały szybko
        self._lib.BASS_SetConfig(0x10500, 1)  # BASS_CONFIG_UPDATEPERIOD
        self._lib.BASS_SetConfig(0x10504, 4)  # BASS_CONFIG_UPDATETHREADS
        self._load_plugins()
        # BASS ASIO ładujemy leniwie (dopiero gdy ktoś wywoła `asio_*`).
        self._asio = None
        self._asio_load_attempted = False
        self._asio_devices: dict[int, dict[str, Any]] = {}

    def stream_create_file(
        self,
        index: int,
        path: Path,
        *,
        allow_loop: bool = False,
        decode: bool = False,
        set_device: bool = True,
    ) -> int:
        try:
            return _streams_ops.stream_create_file(
                self,
                index,
                path,
                allow_loop=allow_loop,
                decode=decode,
                set_device=set_device,
            )
        except BassNotAvailable as exc:
            if "BASS_StreamCreateFile" not in str(exc):
                raise
            if path.suffix.lower() not in TRANSCODE_EXTENSIONS:
                raise

            wav_path = transcode_source_to_wav(path)
            try:
                stream = _streams_ops.stream_create_file(
                    self,
                    index,
                    wav_path,
                    allow_loop=allow_loop,
                    decode=decode,
                    set_device=set_device,
                )
            except Exception:
                try:
                    wav_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise
            with self._global_lock:
                self._transcoded_streams[stream] = wav_path
            return stream

    def stream_free(self, stream: int) -> None:
        _streams_ops.stream_free(self, stream)
        wav_path: Path | None = None
        with self._global_lock:
            wav_path = self._transcoded_streams.pop(stream, None)
        if wav_path is not None:
            try:
                wav_path.unlink(missing_ok=True)
            except Exception:
                pass

    @classmethod
    def instance(cls) -> "BassManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    def _ensure_asio(self):
        if self._asio is not None:
            return self._asio
        if self._asio_load_attempted:
            raise BassNotAvailable("BASS ASIO not available")
        self._asio_load_attempted = True
        try:
            from .asio_native import _BassAsioLibrary

            self._asio = _BassAsioLibrary()
        except BassNotAvailable:
            self._asio = None
            raise
        except Exception as exc:  # pragma: no cover - defensywne
            self._asio = None
            raise BassNotAvailable("BASS ASIO not available") from exc
        return self._asio

    def _load_plugins(self) -> None:
        # próbuj automatycznie załadować najpopularniejsze pluginy (mp3, aac)
        names = ["bassflac", "bass_aac", "bassopus"]
        search_paths: list[Path] = []
        env_path = os.environ.get("BASS_LIBRARY_PATH")
        audio_dir = Path(__file__).resolve().parents[1]
        search_paths.extend(
            [
                Path.cwd(),
                audio_dir,
                audio_dir / "vendor",
                audio_dir / "vendor" / ("windows" if sys.platform.startswith("win") else "linux"),
            ]
        )
        if env_path:
            search_paths.append(Path(env_path))
        search_paths.append(Path.cwd() / "src/sara/audio/vendor/windows")

        def _try_load(candidate: Path) -> bool:
            try:
                # spróbuj wide na Windows, inaczej utf-8 bytes
                handle = None
                if sys.platform.startswith("win"):
                    try:
                        handle = self._lib.BASS_PluginLoad(str(candidate), 0)
                    except Exception:
                        handle = None
                if not handle:
                    try:
                        handle = self._lib.BASS_PluginLoad(str(candidate).encode("utf-8"), 0)
                    except Exception:
                        handle = None
                if handle:
                    logger.debug("BASS plugin loaded: %s", candidate)
                    return True
                code = self._lib.BASS_ErrorGetCode()
                logger.debug("BASS plugin %s load failed, code=%s", candidate, code)
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("BASS plugin %s load error: %s", candidate, exc)
            return False

        for name in names:
            file_names = [f"{name}.dll", f"lib{name}.so", f"lib{name}.dylib", f"{name}.so"]
            for directory in search_paths:
                for fname in file_names:
                    candidate = directory / fname
                    if not candidate.exists():
                        continue
                    if _try_load(candidate):
                        break
                else:
                    continue
                break

    def _set_device(self, index: int) -> None:
        if not self._lib.BASS_SetDevice(index):
            code = self._lib.BASS_ErrorGetCode()
            raise BassNotAvailable(f"BASS_SetDevice({index}) nie powiodło się (kod {code})")
