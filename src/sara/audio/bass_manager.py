"""BASS manager (device lifecycle, stream helpers).

Extracted from `sara.audio.bass` to keep the high-level module smaller.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, List, Optional, TYPE_CHECKING

from sara.audio.bass_asio_native import _BassAsioLibrary, _BASS_ASIO_DEVICEINFO
from sara.audio.bass_native import BassNotAvailable, _BassConstants, _BASS_DEVICEINFO, _BassLibrary

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from sara.audio.engine import AudioDevice


class _DeviceContext:
    def __init__(self, manager: "BassManager", index: int):
        self._manager = manager
        self.index = index

    def release(self) -> None:
        self._manager._release_device(self.index)


class _AsioDeviceContext:
    def __init__(self, manager: "BassManager", index: int):
        self._manager = manager
        self.index = index

    def release(self) -> None:
        self._manager._release_asio_device(self.index)


class BassManager:
    """Singleton zarządzający dostępem do BASS."""

    _instance_lock = threading.Lock()
    _instance: Optional["BassManager"] = None

    def __init__(self) -> None:
        lib_wrapper = _BassLibrary()
        self._lib = lib_wrapper.handle
        self._sync_type = lib_wrapper.sync_proc_type
        self._stream_create_file = getattr(self._lib, "BASS_StreamCreateFile", None)
        self._stream_uses_wchar = sys.platform.startswith("win")
        self._devices: dict[int, dict[str, Any]] = {}
        self._global_lock = threading.Lock()
        # skróć opóźnienie aktualizacji, żeby pętle reagowały szybko
        self._lib.BASS_SetConfig(0x10500, 1)  # BASS_CONFIG_UPDATEPERIOD
        self._lib.BASS_SetConfig(0x10504, 4)  # BASS_CONFIG_UPDATETHREADS
        self._load_plugins()
        # opcjonalnie załaduj BASS ASIO (gdy dostępny)
        try:
            self._asio = _BassAsioLibrary()
        except Exception:
            self._asio = None
        self._asio_devices: dict[int, dict[str, Any]] = {}

    @classmethod
    def instance(cls) -> "BassManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    def list_asio_devices(self) -> List["AudioDevice"]:
        from sara.audio.engine import AudioDevice, BackendType

        devices: List[AudioDevice] = []
        if self._asio is None:
            return devices
        idx = 0
        info = _BASS_ASIO_DEVICEINFO()
        while self._asio._lib.BASS_ASIO_GetDeviceInfo(idx, ctypes.byref(info)):
            name = info.name.decode("utf-8", errors="ignore") if info.name else f"ASIO {idx}"
            # tworzymy standardowe pary kanałów stereo (0/1, 2/3, 4/5, 6/7)
            for ch in (0, 2, 4, 6):
                devices.append(
                    AudioDevice(
                        id=f"bass-asio:{idx}:{ch}",
                        name=f"{name} ch{ch+1}-{ch+2}",
                        backend=BackendType.BASS_ASIO,
                        raw_index=idx,
                        is_default=False,
                    )
                )
            idx += 1
        return devices

    def acquire_asio_device(self, index: int) -> _AsioDeviceContext:
        if self._asio is None:
            raise BassNotAvailable("BASS ASIO not available")
        with self._global_lock:
            data = self._asio_devices.setdefault(index, {"ref": 0, "init": False})
            data["ref"] += 1
            if not data["init"]:
                code = self._asio._lib.BASS_ASIO_Init(index, 0)
                if not code:
                    code = self._asio._lib.BASS_ASIO_ErrorGetCode()
                    raise BassNotAvailable(f"BASS_ASIO_Init({index}) nie powiodło się (kod {code})")
                data["init"] = True
        self._asio._lib.BASS_ASIO_SetDevice(index)
        return _AsioDeviceContext(self, index)

    def _release_asio_device(self, index: int) -> None:
        if self._asio is None:
            return
        with self._global_lock:
            data = self._asio_devices.get(index)
            if not data:
                return
            data["ref"] = max(0, int(data["ref"]) - 1)
            if data["ref"] <= 0 and data.get("init"):
                try:
                    self._asio._lib.BASS_ASIO_SetDevice(index)
                    self._asio._lib.BASS_ASIO_Free()
                except Exception:  # pylint: disable=broad-except
                    pass
                data["init"] = False

    def asio_set_device(self, index: int) -> None:
        if self._asio is None:
            raise BassNotAvailable("BASS ASIO not available")
        if not self._asio._lib.BASS_ASIO_SetDevice(index):
            code = self._asio._lib.BASS_ASIO_ErrorGetCode()
            raise BassNotAvailable(f"BASS_ASIO_SetDevice({index}) nie powiodło się (kod {code})")

    def asio_channel_reset(self, is_input: bool, channel: int, flags: int = 0) -> None:
        if self._asio is None:
            raise BassNotAvailable("BASS ASIO not available")
        self._asio._lib.BASS_ASIO_ChannelReset(bool(is_input), channel, flags)

    def asio_channel_enable_bass(self, is_input: bool, channel: int, bass_channel: int, join: bool) -> None:
        if self._asio is None:
            raise BassNotAvailable("BASS ASIO not available")
        if not self._asio._lib.BASS_ASIO_ChannelEnableBASS(bool(is_input), channel, bass_channel, bool(join)):
            code = self._asio._lib.BASS_ASIO_ErrorGetCode()
            raise BassNotAvailable(f"BASS_ASIO_ChannelEnableBASS nie powiodło się (kod {code})")

    def asio_channel_join(self, is_input: bool, channel: int, join_channel: int) -> None:
        if self._asio is None:
            raise BassNotAvailable("BASS ASIO not available")
        self._asio._lib.BASS_ASIO_ChannelJoin(bool(is_input), channel, join_channel)

    def asio_channel_set_volume(self, is_input: bool, channel: int, volume: float) -> None:
        if self._asio is None:
            raise BassNotAvailable("BASS ASIO not available")
        self._asio._lib.BASS_ASIO_ChannelSetVolume(bool(is_input), channel, ctypes.c_float(volume))

    def asio_channel_set_rate(self, is_input: bool, channel: int, rate: float) -> None:
        if self._asio is None:
            raise BassNotAvailable("BASS ASIO not available")
        self._asio._lib.BASS_ASIO_ChannelSetRate(bool(is_input), channel, ctypes.c_double(rate))

    def asio_start(self, samplerate: float) -> None:
        if self._asio is None:
            raise BassNotAvailable("BASS ASIO not available")
        if not self._asio._lib.BASS_ASIO_Start(ctypes.c_double(samplerate)):
            code = self._asio._lib.BASS_ASIO_ErrorGetCode()
            raise BassNotAvailable(f"BASS_ASIO_Start nie powiodło się (kod {code})")

    def asio_stop(self) -> None:
        if self._asio is None:
            return
        self._asio._lib.BASS_ASIO_Stop()

    def asio_is_started(self) -> bool:
        if self._asio is None:
            return False
        return bool(self._asio._lib.BASS_ASIO_IsStarted())

    def acquire_device(self, index: int) -> _DeviceContext:
        with self._global_lock:
            data = self._devices.setdefault(index, {"ref": 0, "init": False})
            data["ref"] += 1
            if not data["init"]:
                code = self._lib.BASS_Init(index, 48000, 0, None, None)
                if not code:
                    code = self._lib.BASS_ErrorGetCode()
                    raise BassNotAvailable(f"BASS_Init({index}) nie powiodło się (kod {code})")
                data["init"] = True
        self._set_device(index)
        return _DeviceContext(self, index)

    def _release_device(self, index: int) -> None:
        with self._global_lock:
            data = self._devices.get(index)
            if not data:
                return
            data["ref"] = max(0, int(data["ref"]) - 1)
            if data["ref"] <= 0 and data.get("init"):
                try:
                    self._set_device(index)
                    self._lib.BASS_Free()
                except Exception:  # pylint: disable=broad-except
                    pass
                data["init"] = False

    def list_devices(self) -> List["AudioDevice"]:
        from sara.audio.engine import AudioDevice, BackendType

        devices: List[AudioDevice] = []
        index = 0
        info = _BASS_DEVICEINFO()
        while self._lib.BASS_GetDeviceInfo(index, ctypes.byref(info)):
            name = info.name.decode("utf-8", errors="ignore") if info.name else f"Device {index}"
            flags = int(info.flags or 0)
            is_default = bool(flags & _BassConstants.DEVICE_DEFAULT)
            enabled = bool(flags & _BassConstants.DEVICE_ENABLED)
            if enabled:
                devices.append(
                    AudioDevice(
                        id=f"bass:{index}",
                        name=name,
                        backend=BackendType.BASS,
                        raw_index=index,
                        is_default=is_default,
                    )
                )
            index += 1
        return devices

    def _load_plugins(self) -> None:
        # próbuj automatycznie załadować najpopularniejsze pluginy (mp3, aac)
        names = ["bassflac", "bass_aac", "bassopus"]
        search_paths: list[Path] = []
        env_path = os.environ.get("BASS_LIBRARY_PATH")
        base_dir = Path(__file__).resolve().parent
        search_paths.extend(
            [
                Path.cwd(),
                base_dir,
                base_dir / "vendor",
                base_dir / "vendor" / ("windows" if sys.platform.startswith("win") else "linux"),
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

    def stream_create_file(
        self,
        index: int,
        path: Path,
        *,
        allow_loop: bool = False,
        decode: bool = False,
        set_device: bool = True,
    ) -> int:
        if set_device:
            self._set_device(index)
        flags = _BassConstants.SAMPLE_FLOAT | _BassConstants.STREAM_PRESCAN
        if allow_loop:
            flags |= _BassConstants.SAMPLE_LOOP
        if decode:
            flags |= _BassConstants.STREAM_DECODE
        last_code = None
        stream = 0
        if self._stream_create_file is None:
            raise BassNotAvailable("BASS_StreamCreateFile not available")
        try:
            if self._stream_uses_wchar:
                stream = self._stream_create_file(
                    False,
                    ctypes.c_wchar_p(str(path)),
                    0,
                    0,
                    flags | _BassConstants.UNICODE,
                )
            else:
                stream = self._stream_create_file(False, str(path).encode("utf-8"), 0, 0, flags)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("BASS stream create error: %s", exc)
        if not stream:
            last_code = self._lib.BASS_ErrorGetCode()
            logger.error(
                "BASS_StreamCreateFile failed code=%s device=%s path=%s wide=%s",
                last_code,
                index,
                path,
                self._stream_uses_wchar,
            )
            raise BassNotAvailable(f"BASS_StreamCreateFile nie powiodło się (kod {last_code})")
        return stream

    def stream_free(self, stream: int) -> None:
        if stream:
            self._lib.BASS_StreamFree(stream)

    def channel_play(self, stream: int, restart: bool = False) -> None:
        if not self._lib.BASS_ChannelPlay(stream, restart):
            code = self._lib.BASS_ErrorGetCode()
            raise BassNotAvailable(f"BASS_ChannelPlay nie powiodło się (kod {code})")

    def channel_pause(self, stream: int) -> None:
        self._lib.BASS_ChannelPause(stream)

    def channel_stop(self, stream: int) -> None:
        self._lib.BASS_ChannelStop(stream)

    def channel_set_position(self, stream: int, seconds: float) -> None:
        pos = self._lib.BASS_ChannelSeconds2Bytes(stream, ctypes.c_double(seconds))
        self._lib.BASS_ChannelSetPosition(stream, pos, _BassConstants.POS_BYTE)

    def channel_get_seconds(self, stream: int) -> float:
        pos = self._lib.BASS_ChannelGetPosition(stream, _BassConstants.POS_BYTE)
        return float(self._lib.BASS_ChannelBytes2Seconds(stream, pos))

    def channel_is_active(self, stream: int) -> bool:
        state = self._lib.BASS_ChannelIsActive(stream)
        return state != _BassConstants.ACTIVE_STOPPED

    def channel_get_length_seconds(self, stream: int) -> float:
        pos = self._lib.BASS_ChannelGetLength(stream, _BassConstants.POS_BYTE)
        return float(self._lib.BASS_ChannelBytes2Seconds(stream, pos))

    def channel_set_volume(self, stream: int, volume: float) -> None:
        volume = max(0.0, min(volume, 1.0))
        self._lib.BASS_ChannelSetAttribute(stream, _BassConstants.ATTRIB_VOL, ctypes.c_float(volume))

    def seconds_to_bytes(self, stream: int, seconds: float) -> int:
        return int(self._lib.BASS_ChannelSeconds2Bytes(stream, ctypes.c_double(seconds)))

    def channel_set_position_bytes(self, stream: int, byte_pos: int) -> None:
        self._lib.BASS_ChannelSetPosition(stream, byte_pos, _BassConstants.POS_BYTE)

    def make_sync_proc(self, func: Callable[[int, int, int, ctypes.c_void_p], None]):
        return self._sync_type(func)

    def channel_set_sync_pos(
        self, stream: int, position_or_seconds: float, proc, *, is_bytes: bool = False, mix_time: bool = True
    ) -> int:
        position = int(position_or_seconds) if is_bytes else self.seconds_to_bytes(stream, float(position_or_seconds))
        flags = _BassConstants.SYNC_POS | (_BassConstants.SYNC_MIXTIME if mix_time else 0)
        handle = self._lib.BASS_ChannelSetSync(stream, flags, position, proc, None)
        if not handle:
            code = self._lib.BASS_ErrorGetCode()
            raise BassNotAvailable(f"BASS_ChannelSetSync nie powiodło się (kod {code})")
        return handle

    def channel_remove_sync(self, stream: int, sync_handle: int) -> None:
        if sync_handle:
            self._lib.BASS_ChannelRemoveSync(stream, sync_handle)

    def channel_set_sync_end(self, stream: int, proc) -> int:
        handle = self._lib.BASS_ChannelSetSync(
            stream,
            _BassConstants.SYNC_END | _BassConstants.SYNC_MIXTIME,
            0,
            proc,
            None,
        )
        if not handle:
            code = self._lib.BASS_ErrorGetCode()
            raise BassNotAvailable(f"BASS_ChannelSetSync (END) nie powiodło się (kod {code})")
        return handle

