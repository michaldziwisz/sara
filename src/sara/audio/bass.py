"""Integracja z biblioteką BASS (jeśli dostępna)."""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

logger = logging.getLogger(__name__)
_DEBUG_LOOP = bool(os.environ.get("SARA_DEBUG_LOOP"))

if TYPE_CHECKING:  # pragma: no cover
    from sara.audio.engine import AudioDevice


class BassNotAvailable(Exception):
    """Wyrzucane, gdy biblioteki BASS nie udało się załadować."""


class _BassConstants:
    DEVICE_ENABLED = 0x0001
    DEVICE_DEFAULT = 0x0002

    SAMPLE_FLOAT = 0x10000
    SAMPLE_LOOP = 0x00004
    STREAM_PRESCAN = 0x20000
    UNICODE = 0x80000000
    STREAM_DECODE = 0x200000

    POS_BYTE = 0
    ATTRIB_VOL = 2

    ACTIVE_STOPPED = 0
    SYNC_POS = 0x00000010
    SYNC_MIXTIME = 0x40000000
    SYNC_ONETIME = 0x20000000
    POS_BYTES = 0
    SYNC_END = 0x00000002


class _BASS_DEVICEINFO(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("driver", ctypes.c_char_p),
        ("flags", ctypes.c_uint),
    ]


class _BassLibrary:
    """Odpowiada za ładowanie biblioteki BASS i definiowanie sygnatur."""

    def __init__(self) -> None:
        self._lib = self._load_library()
        self._configure_prototypes()
        self.stream_create_file_func_w = getattr(self._lib, "BASS_StreamCreateFileW", None)
        self.stream_create_file_func_a = getattr(self._lib, "BASS_StreamCreateFile", None)
        self.stream_create_uses_wchar = bool(self.stream_create_file_func_w) and sys.platform.startswith("win")

    @staticmethod
    def _possible_library_names() -> List[str]:
        if sys.platform.startswith("win"):
            return ["bass.dll"]
        if sys.platform == "darwin":
            return ["libbass.dylib", "bass.dylib"]
        return ["libbass.so", "bass.so"]

    def _load_library(self):
        errors: list[str] = []
        names = self._possible_library_names()
        search_paths: List[Path] = []
        env_path = os.environ.get("BASS_LIBRARY_PATH")
        if env_path:
            search_paths.append(Path(env_path))
        # katalog projektu (np. vendor)
        base_dir = Path(__file__).resolve().parent
        search_paths.append(Path.cwd())
        search_paths.append(base_dir)
        search_paths.append(base_dir / "vendor")
        platform_dir = base_dir / "vendor" / ("windows" if sys.platform.startswith("win") else "linux")
        search_paths.append(platform_dir)
        if getattr(sys, "frozen", False):  # pragma: no cover - tylko w buildach
            try:
                search_paths.append(Path(sys.executable).resolve().parent)
            except Exception:  # pragma: no cover - fallback
                pass
            try:
                base_tmp = Path(getattr(sys, "_MEIPASS"))
                search_paths.append(base_tmp)
            except Exception:
                pass
        for directory in search_paths:
            for name in names:
                candidate = directory / name
                if candidate.exists():
                    try:
                        if sys.platform.startswith("win") and hasattr(os, "add_dll_directory"):
                            with os.add_dll_directory(str(candidate.parent)):
                                return ctypes.WinDLL(str(candidate))
                        return ctypes.WinDLL(str(candidate)) if sys.platform.startswith("win") else ctypes.CDLL(str(candidate))
                    except OSError as exc:  # pragma: no cover - zależne od środowiska
                        errors.append(f"{candidate}: {exc}")
        for name in names:
            try:
                return ctypes.WinDLL(name) if sys.platform.startswith("win") else ctypes.CDLL(name)
            except OSError as exc:  # pragma: no cover - zależne od środowiska
                errors.append(f"{name}: {exc}")
        search_list = ", ".join(str(path) for path in search_paths)
        error_list = "; ".join(errors)
        logger.warning("BASS niedostępny. Sprawdzone ścieżki: %s; błędy: %s", search_list, error_list)
        raise BassNotAvailable("Nie znaleziono biblioteki BASS (ustaw zmienną BASS_LIBRARY_PATH)")

    def _configure_prototypes(self) -> None:
        lib = self._lib
        DWORD = ctypes.c_uint
        QWORD = ctypes.c_ulonglong
        BOOL = ctypes.c_bool
        USES_WCHAR = sys.platform.startswith("win")

        lib.BASS_SetConfig.argtypes = [DWORD, DWORD]
        lib.BASS_SetConfig.restype = BOOL

        lib.BASS_Init.argtypes = [ctypes.c_int, DWORD, DWORD, ctypes.c_void_p, ctypes.c_void_p]
        lib.BASS_Init.restype = BOOL

        lib.BASS_Free.argtypes = []
        lib.BASS_Free.restype = BOOL

        lib.BASS_SetDevice.argtypes = [DWORD]
        lib.BASS_SetDevice.restype = BOOL

        lib.BASS_GetDeviceInfo.argtypes = [DWORD, ctypes.POINTER(_BASS_DEVICEINFO)]
        lib.BASS_GetDeviceInfo.restype = BOOL

        if hasattr(lib, "BASS_StreamCreateFile"):
            lib.BASS_StreamCreateFile.argtypes = [BOOL, ctypes.c_void_p, QWORD, QWORD, DWORD]
            lib.BASS_StreamCreateFile.restype = DWORD

        lib.BASS_StreamFree.argtypes = [DWORD]
        lib.BASS_StreamFree.restype = BOOL

        lib.BASS_ChannelPlay.argtypes = [DWORD, BOOL]
        lib.BASS_ChannelPlay.restype = BOOL

        lib.BASS_ChannelPause.argtypes = [DWORD]
        lib.BASS_ChannelPause.restype = BOOL

        lib.BASS_ChannelStop.argtypes = [DWORD]
        lib.BASS_ChannelStop.restype = BOOL

        lib.BASS_ChannelGetPosition.argtypes = [DWORD, DWORD]
        lib.BASS_ChannelGetPosition.restype = QWORD

        lib.BASS_ChannelSetPosition.argtypes = [DWORD, QWORD, DWORD]
        lib.BASS_ChannelSetPosition.restype = BOOL

        lib.BASS_ChannelSeconds2Bytes.argtypes = [DWORD, ctypes.c_double]
        lib.BASS_ChannelSeconds2Bytes.restype = QWORD

        lib.BASS_ChannelBytes2Seconds.argtypes = [DWORD, QWORD]
        lib.BASS_ChannelBytes2Seconds.restype = ctypes.c_double

        lib.BASS_ChannelIsActive.argtypes = [DWORD]
        lib.BASS_ChannelIsActive.restype = DWORD

        lib.BASS_ChannelSetAttribute.argtypes = [DWORD, DWORD, ctypes.c_float]
        lib.BASS_ChannelSetAttribute.restype = BOOL

        lib.BASS_ChannelGetAttribute.argtypes = [DWORD, DWORD, ctypes.POINTER(ctypes.c_float)]
        lib.BASS_ChannelGetAttribute.restype = BOOL

        lib.BASS_PluginLoad.argtypes = [ctypes.c_char_p, DWORD]
        lib.BASS_PluginLoad.restype = ctypes.c_void_p

        lib.BASS_ErrorGetCode.argtypes = []
        lib.BASS_ErrorGetCode.restype = ctypes.c_int

        sync_proc = ctypes.CFUNCTYPE(None, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p)
        lib.BASS_ChannelSetSync.argtypes = [DWORD, DWORD, QWORD, sync_proc, ctypes.c_void_p]
        lib.BASS_ChannelSetSync.restype = DWORD
        lib.BASS_ChannelRemoveSync.argtypes = [DWORD, DWORD]
        lib.BASS_ChannelRemoveSync.restype = BOOL

        self._lib = lib
        self.sync_proc_type = sync_proc

    @property
    def handle(self):
        return self._lib

    @property
    def handle(self):  # pragma: no cover - dostęp kontrolowany
        return self._lib


class _BassAsioLibrary:
    """Ładowanie dodatku BASS ASIO (bassasio.dll)."""

    def __init__(self) -> None:
        self._lib = self._load_library()
        self._configure_prototypes()

    @staticmethod
    def _possible_names() -> List[str]:
        if sys.platform.startswith("win"):
            return ["bassasio.dll"]
        if sys.platform == "darwin":
            return ["libbassasio.dylib", "bassasio.dylib"]
        return ["libbassasio.so", "bassasio.so"]

    def _load_library(self):
        errors: list[str] = []
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
        for directory in search_paths:
            for name in self._possible_names():
                candidate = directory / name
                if candidate.exists():
                    try:
                        if sys.platform.startswith("win") and hasattr(os, "add_dll_directory"):
                            with os.add_dll_directory(str(candidate.parent)):
                                return ctypes.WinDLL(str(candidate))
                        return ctypes.WinDLL(str(candidate)) if sys.platform.startswith("win") else ctypes.CDLL(str(candidate))
                    except OSError as exc:
                        errors.append(f"{candidate}: {exc}")
        raise BassNotAvailable(f"Nie znaleziono biblioteki BASS ASIO ({'; '.join(errors)})")

    def _configure_prototypes(self) -> None:
        lib = self._lib
        DWORD = ctypes.c_uint
        BOOL = ctypes.c_bool
        QWORD = ctypes.c_ulonglong
        lib.BASS_ASIO_GetDeviceInfo.argtypes = [ctypes.c_int, ctypes.c_void_p]
        lib.BASS_ASIO_GetDeviceInfo.restype = BOOL
        lib.BASS_ASIO_ErrorGetCode.argtypes = []
        lib.BASS_ASIO_ErrorGetCode.restype = DWORD
        lib.BASS_ASIO_Init.argtypes = [ctypes.c_int, ctypes.c_uint]
        lib.BASS_ASIO_Init.restype = BOOL
        lib.BASS_ASIO_Free.argtypes = []
        lib.BASS_ASIO_Free.restype = BOOL
        lib.BASS_ASIO_SetDevice.argtypes = [ctypes.c_int]
        lib.BASS_ASIO_SetDevice.restype = BOOL
        lib.BASS_ASIO_ChannelReset.argtypes = [ctypes.c_int, ctypes.c_int, DWORD]
        lib.BASS_ASIO_ChannelReset.restype = BOOL
        lib.BASS_ASIO_ChannelEnableBASS.argtypes = [BOOL, ctypes.c_int, DWORD, BOOL]
        lib.BASS_ASIO_ChannelEnableBASS.restype = BOOL
        lib.BASS_ASIO_ChannelJoin.argtypes = [BOOL, ctypes.c_int, ctypes.c_int]
        lib.BASS_ASIO_ChannelJoin.restype = BOOL
        lib.BASS_ASIO_ChannelSetVolume.argtypes = [BOOL, DWORD, ctypes.c_float]
        lib.BASS_ASIO_ChannelSetVolume.restype = BOOL
        lib.BASS_ASIO_Start.argtypes = [ctypes.c_double]
        lib.BASS_ASIO_Start.restype = BOOL
        lib.BASS_ASIO_Stop.argtypes = []
        lib.BASS_ASIO_Stop.restype = BOOL
        lib.BASS_ASIO_IsStarted.argtypes = []
        lib.BASS_ASIO_IsStarted.restype = BOOL
        lib.BASS_ASIO_ChannelSetRate.argtypes = [BOOL, DWORD, ctypes.c_double]
        lib.BASS_ASIO_ChannelSetRate.restype = BOOL


class _BASS_ASIO_DEVICEINFO(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("driver", ctypes.c_char_p),
        ("flags", ctypes.c_uint),
    ]

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
            if not data["init"]:
                if not self._asio._lib.BASS_ASIO_Init(index, 0):
                    code = self._asio._lib.BASS_ASIO_ErrorGetCode()
                    raise BassNotAvailable(f"BASS_ASIO_Init({index}) nie powiodło się (kod {code})")
                data["init"] = True
            data["ref"] += 1
        return _AsioDeviceContext(self, index)

    def _release_asio_device(self, index: int) -> None:
        with self._global_lock:
            data = self._asio_devices.get(index)
            if not data:
                return
            data["ref"] = max(0, data["ref"] - 1)

    def _set_asio_device(self, index: int) -> None:
        if self._asio is None:
            raise BassNotAvailable("BASS ASIO not available")
        if not self._asio._lib.BASS_ASIO_SetDevice(index):
            code = self._asio._lib.BASS_ASIO_ErrorGetCode()
            raise BassNotAvailable(f"BASS_ASIO_SetDevice({index}) nie powiodło się (kod {code})")

    def asio_play_stream(self, index: int, stream: int, channel_start: int = 0) -> None:
        if self._asio is None:
            raise BassNotAvailable("BASS ASIO not available")
        self._set_asio_device(index)
        lib = self._asio._lib
        base = max(0, int(channel_start))
        # wyczyść docelowe kanały, ale nie zatrzymujemy całego ASIO (żeby nie rwać innych wyjść)
        for ch in (base, base + 1):
            try:
                lib.BASS_ASIO_ChannelReset(False, ch, 0xFFFFFFFF)
            except Exception:
                pass
        # włącz BASS decoder jako źródło
        base = max(0, int(channel_start))
        if not lib.BASS_ASIO_ChannelEnableBASS(False, base, stream, True):
            code = lib.BASS_ASIO_ErrorGetCode()
            raise BassNotAvailable(f"BASS_ASIO_ChannelEnableBASS nie powiodło się (kod {code})")
        # stereo: dołącz prawy kanał do lewego (jeśli jest)
        if not lib.BASS_ASIO_ChannelJoin(False, base + 1, base):
            # jeśli join się nie uda (np. brak drugiego kanału), pomiń
            pass
        # uruchom, jeśli jeszcze nie gra
        try:
            started = lib.BASS_ASIO_IsStarted()
        except Exception:
            started = False
        if not started:
            if not lib.BASS_ASIO_Start(0):
                code = lib.BASS_ASIO_ErrorGetCode()
                raise BassNotAvailable(f"BASS_ASIO_Start nie powiodło się (kod {code})")

    def asio_stop(self, index: int) -> None:
        if self._asio is None:
            return
        try:
            self._set_asio_device(index)
            self._asio._lib.BASS_ASIO_Stop()
            self._asio._lib.BASS_ASIO_ChannelReset(False, -1, 0xFFFFFFFF)
        except Exception:
            pass

    def asio_is_active(self, index: int) -> bool:
        if self._asio is None:
            return False
        try:
            self._set_asio_device(index)
            return bool(self._asio._lib.BASS_ASIO_IsStarted())
        except Exception:
            return False

    def asio_set_volume(self, index: int, channel_start: int, volume: float) -> None:
        if self._asio is None:
            return
        vol = max(0.0, min(volume, 1.0))
        self._set_asio_device(index)
        base = max(0, int(channel_start))
        self._asio._lib.BASS_ASIO_ChannelSetVolume(False, base, ctypes.c_float(vol))
        try:
            self._asio._lib.BASS_ASIO_ChannelSetVolume(False, base + 1, ctypes.c_float(vol))
        except Exception:
            pass

    def list_devices(self) -> List["AudioDevice"]:
        from sara.audio.engine import AudioDevice, BackendType

        devices: List[AudioDevice] = []
        index = 0
        info = _BASS_DEVICEINFO()
        while self._lib.BASS_GetDeviceInfo(index, ctypes.byref(info)):
            flags = info.flags
            enabled = bool(flags & _BassConstants.DEVICE_ENABLED)
            name_bytes = info.name or b""
            name = f"Device {index}"
            if name_bytes:
                try:
                    name = name_bytes.decode("utf-8")
                except Exception:
                    try:
                        name = name_bytes.decode("mbcs")
                    except Exception:
                        name = name_bytes.decode("latin-1", errors="ignore")
            if enabled:
                devices.append(
                    AudioDevice(
                        id=f"bass:{index}",
                        name=name,
                        backend=BackendType.BASS,
                        raw_index=index,
                        is_default=bool(flags & _BassConstants.DEVICE_DEFAULT),
                        # default_samplerate doklejone do id do późniejszego użycia
                    )
                )
            index += 1
        return devices

    def acquire_device(self, index: int, samplerate: int | None = None) -> _DeviceContext:
        with self._global_lock:
            data = self._devices.setdefault(index, {"ref": 0, "init": False})
            if not data["init"]:
                rate = int(samplerate) if samplerate and samplerate > 0 else 44100
                success = self._lib.BASS_Init(index, rate, 0, None, None)
                if not success:
                    code = self._lib.BASS_ErrorGetCode()
                    raise BassNotAvailable(f"BASS_Init({index}) nie powiodło się (kod {code})")
                data["init"] = True
            data["ref"] += 1
        return _DeviceContext(self, index)

    def _release_device(self, index: int) -> None:
        with self._global_lock:
            data = self._devices.get(index)
            if not data:
                return
            data["ref"] = max(0, data["ref"] - 1)
            # pozostawiamy urządzenie zainicjalizowane na przyszłość

    def ensure_device(self, index: int, samplerate: int | None = None) -> None:
        self.acquire_device(index, samplerate).release()

    def _load_plugins(self) -> None:
        # spróbuj załadować popularne pluginy (FLAC/AAC/OPUS) jeśli są dostępne
        names = ["bassflac", "bass_aac", "bassopus", "basswv", "bassalac", "bassape", "bass_ac3", "bass_mpc", "bass_spx"]
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
        allow_loop: bool = True,
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
                stream = self._stream_create_file(False, ctypes.c_wchar_p(str(path)), 0, 0, flags | _BassConstants.UNICODE)
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

    def channel_set_sync_pos(self, stream: int, position_or_seconds: float, proc, *, is_bytes: bool = False) -> int:
        position = (
            int(position_or_seconds)
            if is_bytes
            else self.seconds_to_bytes(stream, float(position_or_seconds))
        )
        handle = self._lib.BASS_ChannelSetSync(
            stream,
            _BassConstants.SYNC_POS | _BassConstants.SYNC_MIXTIME,
            position,
            proc,
            None,
        )
        if not handle:
            code = self._lib.BASS_ErrorGetCode()
            raise BassNotAvailable(f"BASS_ChannelSetSync nie powiodło się (kod {code})")
        return handle

    def channel_remove_sync(self, stream: int, sync_handle: int) -> None:
        if sync_handle:
            self._lib.BASS_ChannelRemoveSync(stream, sync_handle)

    def channel_set_sync_end(self, stream: int, proc) -> int:
        handle = self._lib.BASS_ChannelSetSync(stream, _BassConstants.SYNC_END | _BassConstants.SYNC_MIXTIME, 0, proc, None)
        if not handle:
            code = self._lib.BASS_ErrorGetCode()
            raise BassNotAvailable(f"BASS_ChannelSetSync (END) nie powiodło się (kod {code})")
        return handle


class BassPlayer:
    """Implementacja Player korzystająca z BASS."""

    # Bardzo mały interwał, żeby zdarzenia miksu/pętli były możliwie precyzyjne.
    _MONITOR_INTERVAL = 0.001

    def __init__(self, manager: BassManager, device_index: int) -> None:
        self._manager = manager
        self._device_index = device_index
        self._device_context: Optional[_DeviceContext] = None
        self._stream: int = 0
        self._current_item_id: Optional[str] = None
        self._gain_factor: float = 1.0
        self._loop_start: Optional[float] = None
        self._loop_end: Optional[float] = None
        self._loop_active: bool = False
        self._loop_sync_handle: int = 0
        self._loop_sync_proc = None
        self._loop_alt_sync_handle: int = 0
        self._loop_alt_sync_proc = None
        self._loop_end_sync_handle: int = 0
        self._loop_end_sync_proc = None
        self._loop_start_bytes: int = 0
        self._loop_end_bytes: int = 0
        self._debug_loop = _DEBUG_LOOP
        self._mix_sync_handle: int = 0
        self._mix_sync_proc = None
        self._mix_callback: Optional[Callable[[], None]] = None
        self._finished_callback: Optional[Callable[[str], None]] = None
        self._progress_callback: Optional[Callable[[str, float], None]] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_stop = threading.Event()
        self._fade_thread: Optional[threading.Thread] = None
        # zachowujemy schowany timer z dawnych implementacji, żeby unikać attribute error
        self._loop_fake_timer = None
        self._last_loop_jump_ts: float = 0.0
        self._loop_guard_enabled: bool = True
        self._last_loop_debug_log: float = 0.0
        # zapewnij kompatybilność, nawet jeśli stary obiekt był zcache'owany
        if not hasattr(self, "_apply_loop_settings"):
            self._apply_loop_settings = lambda: None  # type: ignore[attr-defined]
        if not hasattr(self, "set_loop"):
            # minimalny set_loop dla starych instancji
            def _compat_set_loop(start_seconds, end_seconds):
                self._loop_start = start_seconds
                self._loop_end = end_seconds
                self._loop_active = bool(
                    start_seconds is not None
                    and end_seconds is not None
                    and end_seconds > start_seconds
                )
            self.set_loop = _compat_set_loop  # type: ignore[attr-defined]

    # --- lifecycle ---
    def play(
        self,
        playlist_item_id: str,
        source_path: str,
        *,
        start_seconds: float = 0.0,
        allow_loop: bool = True,
        mix_trigger_seconds: Optional[float] = None,
        on_mix_trigger: Optional[Callable[[], None]] = None,
    ) -> Optional[threading.Event]:
        self.stop()
        self._current_item_id = playlist_item_id
        path = Path(source_path)
        self._device_context = self._manager.acquire_device(self._device_index)
        self._stream = self._manager.stream_create_file(self._device_index, path, allow_loop=allow_loop)
        if start_seconds > 0:
            self._manager.channel_set_position(self._stream, start_seconds)
        self._apply_gain()
        self._manager.channel_play(self._stream, False)
        self._loop_active = bool(self._loop_start is not None and self._loop_end is not None)
        self._last_loop_jump_ts = 0.0
        self._apply_loop_settings()
        self._apply_mix_trigger(mix_trigger_seconds, on_mix_trigger)
        self._start_monitor()
        return None

    def pause(self) -> None:
        if self._stream:
            self._manager.channel_pause(self._stream)

    def stop(self, *, _from_fade: bool = False) -> None:
        self._monitor_stop.set()
        if self._fade_thread and self._fade_thread.is_alive() and not _from_fade:
            self._fade_thread.join(timeout=0.5)
        if not _from_fade:
            self._fade_thread = None
        if self._stream:
            try:
                if getattr(self, "_use_asio", False):
                    self._manager.asio_stop(self._device_index)
            except Exception:
                pass
            self._manager.channel_stop(self._stream)
            if self._loop_sync_handle:
                self._manager.channel_remove_sync(self._stream, self._loop_sync_handle)
                self._loop_sync_handle = 0
                self._loop_sync_proc = None
            if hasattr(self, "_loop_end_sync_handle") and self._loop_end_sync_handle:
                self._manager.channel_remove_sync(self._stream, self._loop_end_sync_handle)
                self._loop_end_sync_handle = 0
            self._loop_end_sync_proc = None
            if hasattr(self, "_loop_alt_sync_handle") and self._loop_alt_sync_handle:
                self._manager.channel_remove_sync(self._stream, self._loop_alt_sync_handle)
                self._loop_alt_sync_handle = 0
                self._loop_alt_sync_proc = None
            if self._mix_sync_handle:
                self._manager.channel_remove_sync(self._stream, self._mix_sync_handle)
                self._mix_sync_handle = 0
                self._mix_sync_proc = None
            self._manager.stream_free(self._stream)
            self._stream = 0
        if self._device_context:
            self._device_context.release()
            self._device_context = None
        if getattr(self, "_asio_context", None):
            self._asio_context.release()
            self._asio_context = None
        self._current_item_id = None
        self._loop_active = False
        if self._monitor_thread and self._monitor_thread.is_alive() and not _from_fade:
            self._monitor_thread.join(timeout=0.5)
        self._monitor_thread = None
        self._monitor_stop.clear()
        if _from_fade:
            self._fade_thread = None

    def _start_monitor(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_stop.clear()

        def _runner() -> None:
            while not self._monitor_stop.is_set():
                try:
                    if self._stream:
                        if self._progress_callback and self._current_item_id:
                            try:
                                pos = self._manager.channel_get_seconds(self._stream)
                                self._progress_callback(self._current_item_id, pos)
                            except Exception:
                                pass
                        # nadzoruj pętlę również po stronie Python, żeby uniknąć pominiętych synców
                        if (
                            self._loop_guard_enabled
                            and self._loop_active
                            and self._loop_end is not None
                            and self._loop_start is not None
                        ):
                            try:
                                pos = self._manager.channel_get_seconds(self._stream)
                                now = time.time()
                                if self._debug_loop and (now - self._last_loop_debug_log) > 0.5:
                                    logger.debug(
                                        "Loop debug: pos=%.6f start=%.6f end=%.6f stream=%s",
                                        pos,
                                        self._loop_start,
                                        self._loop_end,
                                        self._stream,
                                    )
                                    self._last_loop_debug_log = now
                                # strażnik awaryjny: reaguje tuż przed końcem, gdy sync nie zadziałał
                                if (now - self._last_loop_jump_ts) > 0.002 and pos >= (self._loop_end - 0.005):
                                    self._last_loop_jump_ts = now
                                    if self._loop_start_bytes:
                                        self._manager.channel_set_position_bytes(self._stream, self._loop_start_bytes)
                                    else:
                                        self._manager.channel_set_position(self._stream, self._loop_start)
                                    if self._debug_loop:
                                        logger.debug(
                                            "Loop debug: python guard jump pos=%.6f start=%.6f end=%.6f",
                                            pos,
                                            self._loop_start,
                                            self._loop_end,
                                        )
                                    continue
                                # jeśli pozycja wyleciała daleko za koniec (np. audio glitch), natychmiast skoryguj
                                if pos > (self._loop_end + 0.02):
                                    self._last_loop_jump_ts = now
                                    if self._loop_start_bytes:
                                        self._manager.channel_set_position_bytes(self._stream, self._loop_start_bytes)
                                    else:
                                        self._manager.channel_set_position(self._stream, self._loop_start)
                                    if self._debug_loop:
                                        logger.debug(
                                            "Loop debug: hard clamp pos=%.6f start=%.6f end=%.6f",
                                            pos,
                                            self._loop_start,
                                            self._loop_end,
                                        )
                                    continue
                            except Exception as exc:
                                if self._debug_loop:
                                    logger.debug("Loop debug: guard check failed: %s", exc)
                        active = self._is_active()
                        if not active:
                            # Jeśli pętla ma być aktywna, próbujemy wznowić bez wyzwalania zakończenia
                            if self._loop_active and self._stream:
                                try:
                                    if self._loop_start_bytes:
                                        self._manager.channel_set_position_bytes(self._stream, self._loop_start_bytes)
                                    # jeśli strumień nie gra, wznów go
                                    try:
                                        self._manager.channel_play(self._stream, False)
                                    except Exception:
                                        pass
                                except Exception as exc:
                                    if self._debug_loop:
                                        logger.debug("Loop debug: monitor restart failed: %s", exc)
                                # nawet jeśli się nie udało, nie zgłaszaj zakończenia – próbuj ponownie
                                time.sleep(self._MONITOR_INTERVAL)
                                continue
                            if self._finished_callback and self._current_item_id:
                                try:
                                    self._finished_callback(self._current_item_id)
                                except Exception:
                                    pass
                            # zwolnij zasoby po naturalnym zakończeniu
                            try:
                                self.stop(_from_fade=True)
                            except Exception:
                                pass
                            break
                    time.sleep(self._MONITOR_INTERVAL)
                except Exception:
                    break
        self._monitor_thread = threading.Thread(target=_runner, daemon=True, name="bass-monitor")
        self._monitor_thread.start()

    def _apply_mix_trigger(self, target_seconds: Optional[float], callback: Optional[Callable[[], None]]) -> None:
        self._mix_callback = callback
        if not target_seconds or not self._stream:
            return
        try:
            target_bytes = self._manager.seconds_to_bytes(self._stream, target_seconds)
        except Exception as exc:
            logger.debug("BASS mix trigger: failed to convert seconds to bytes: %s", exc)
            return

        def _sync_proc(hsync, channel, data, user):  # pragma: no cover - C callback
            if self._mix_callback:
                try:
                    self._mix_callback()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("BASS mix trigger callback error: %s", exc)

        self._mix_sync_proc = self._manager.make_sync_proc(_sync_proc)
        try:
            self._mix_sync_handle = self._manager.channel_set_sync_pos(
                self._stream, target_bytes, self._mix_sync_proc, is_bytes=True
            )
        except Exception as exc:
            logger.debug("BASS mix trigger: failed to set sync: %s", exc)
            self._mix_sync_proc = None
            self._mix_sync_handle = 0

    def fade_out(self, duration: float) -> None:
        if duration <= 0 or not self._stream:
            self.stop()
            return

        target_stream = self._stream

        def _runner(target: int) -> None:
            steps = max(4, int(duration / 0.05))
            interrupted = False
            try:
                initial = self._gain_factor
                for i in range(steps):
                    if self._stream != target:
                        interrupted = True
                        break
                    factor = initial * (1.0 - float(i + 1) / steps)
                    try:
                        self._manager.channel_set_volume(target, factor)
                    except Exception as exc:
                        logger.debug("BASS fade step failed: %s", exc)
                        interrupted = True
                        break
                    time.sleep(duration / steps)
            finally:
                if interrupted or self._stream != target:
                    try:
                        self._manager.channel_set_volume(target, self._gain_factor)
                    except Exception:
                        pass
                else:
                    self.stop(_from_fade=True)

        self._fade_thread = threading.Thread(target=_runner, args=(target_stream,), daemon=True)
        self._fade_thread.start()

    def set_finished_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        self._finished_callback = callback

    def set_progress_callback(self, callback: Optional[Callable[[str, float], None]]) -> None:
        self._progress_callback = callback

    def set_mix_callback(self, callback: Optional[Callable[[], None]]) -> None:
        self._mix_callback = callback

    def set_gain_db(self, gain_db: Optional[float]) -> None:
        if gain_db is None:
            self._gain_factor = 1.0
        else:
            try:
                gain = max(min(gain_db, 18.0), -60.0)
                self._gain_factor = float(10 ** (gain / 20.0))
            except Exception:  # pragma: no cover - defensywne
                self._gain_factor = 1.0
        self._apply_gain()

    def _apply_gain(self) -> None:
        if self._stream:
            self._manager.channel_set_volume(self._stream, self._gain_factor)
    def _is_active(self) -> bool:
        return self._manager.channel_is_active(self._stream)

    def is_active(self) -> bool:
        return self._is_active()


class BassAsioPlayer(BassPlayer):
    """Player wykorzystujący BASS ASIO (bassasio.dll)."""

    def __init__(self, manager: BassManager, device_index: int, channel_start: int = 0) -> None:
        super().__init__(manager, device_index)
        self._channel_start = max(0, channel_start)
        self._asio_context: Optional[_AsioDeviceContext] = None
        self._stream_total_seconds: float = 0.0
        self._use_asio = True
        # osobny kontekst BASS do tworzenia strumienia decode (no-sound)
        self._decode_device_context: Optional[_DeviceContext] = None
        self._gain_factor = 1.0
        # przy BASS ASIO włączamy guard oraz sync – oba dla pewności
        self._loop_guard_enabled = True
        # własne callbacki ASIO
        self._asio_finished_callback: Optional[Callable[[str], None]] = None
        self._asio_mix_callback: Optional[Callable[[], None]] = None
        self._asio_mix_trigger = None

    def _is_active(self) -> bool:
        try:
            if self._progress_callback and self._current_item_id:
                pos = self._manager.channel_get_seconds(self._stream)
                self._progress_callback(self._current_item_id, pos)
        except Exception:
            pass
        return self._manager.asio_is_active(self._device_index)

    def is_active(self) -> bool:
        return self._is_active()

    def play(
        self,
        playlist_item_id: str,
        source_path: str,
        *,
        start_seconds: float = 0.0,
        allow_loop: bool = True,
        mix_trigger_seconds: Optional[float] = None,
        on_mix_trigger: Optional[Callable[[], None]] = None,
    ) -> Optional[threading.Event]:
        # ASIO wymaga kanału w trybie decode
        self.stop()
        self._current_item_id = playlist_item_id
        path = Path(source_path)
        self._asio_context = self._manager.acquire_asio_device(self._device_index)
        decode_device_index = 0  # BASS „No sound”
        self._decode_device_context = None
        try:
            self._decode_device_context = self._manager.acquire_device(decode_device_index)
        except Exception as exc:
            logger.debug("BASS ASIO: nie udało się zainicjować urządzenia decode %s: %s", decode_device_index, exc)
        self._stream = self._manager.stream_create_file(
            decode_device_index,
            path,
            # ustaw SAMPLE_LOOP, żeby strumień decode nie zatrzymał się po dojściu do końca
            allow_loop=True,
            decode=True,
            set_device=self._decode_device_context is not None,
        )
        if start_seconds > 0:
            self._manager.channel_set_position(self._stream, start_seconds)
        self._apply_gain()
        self._loop_active = bool(self._loop_start is not None and self._loop_end is not None)
        self._last_loop_jump_ts = 0.0
        try:
            self._stream_total_seconds = self._manager.channel_get_length_seconds(self._stream)
        except Exception:
            self._stream_total_seconds = 0.0
        self._apply_loop_settings()
        self._apply_mix_trigger(mix_trigger_seconds, on_mix_trigger)
        # zamiast ChannelPlay włączamy ASIO render BASS decode
        try:
            self._manager.asio_play_stream(self._device_index, self._stream, channel_start=self._channel_start)
        except Exception as exc:
            logger.error(
                "BASS ASIO start failed device=%s ch=%s err=%s",
                self._device_index,
                self._channel_start,
                exc,
            )
            self.stop()
            raise
        self._start_monitor()
        return None

    def stop(self, *, _from_fade: bool = False) -> None:
        try:
            self._manager.asio_stop(self._device_index)
        except Exception:
            pass
        super().stop(_from_fade=_from_fade)
        if self._asio_context:
            self._asio_context.release()
            self._asio_context = None
        if self._decode_device_context:
            try:
                self._decode_device_context.release()
            except Exception:
                pass
            self._decode_device_context = None

    def _apply_gain(self) -> None:
        try:
            self._manager.asio_set_volume(self._device_index, self._channel_start, self._gain_factor)
        except Exception:
            pass

    def fade_out(self, duration: float) -> None:
        if not self._stream:
            return
        target_stream = self._stream
        if self._fade_thread and self._fade_thread.is_alive():
            return

        def _runner():
            nonlocal target_stream
            steps = max(4, int(duration / 0.05))
            interrupted = False
            initial = self._gain_factor
            try:
                if self._debug_loop:
                    logger.debug("ASIO fade start duration=%.3f gain=%.3f", duration, initial)
                for i in range(steps):
                    if self._stream != target_stream:
                        interrupted = True
                        break
                    factor = initial * (1.0 - float(i + 1) / steps)
                    self._gain_factor = factor
                    try:
                        self._manager.asio_set_volume(self._device_index, self._channel_start, factor)
                    except Exception:
                        interrupted = True
                        break
                    time.sleep(duration / steps)
            finally:
                if not interrupted and self._stream == target_stream:
                    self.stop(_from_fade=True)

        self._fade_thread = threading.Thread(target=_runner, daemon=True)
        self._fade_thread.start()

    def set_loop(self, start_seconds: Optional[float], end_seconds: Optional[float]) -> None:
        if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
            self._loop_start = None
            self._loop_end = None
            self._loop_active = False
            self._last_loop_jump_ts = 0.0
            if self._loop_sync_handle and self._stream:
                self._manager.channel_remove_sync(self._stream, self._loop_sync_handle)
            self._loop_sync_handle = 0
            self._loop_sync_proc = None
            return
        self._loop_start = start_seconds
        self._loop_end = end_seconds
        self._loop_active = True
        self._last_loop_jump_ts = 0.0
        self._apply_loop_settings()

    def _apply_loop_settings(self) -> None:
        if not self._stream:
            return
        if self._loop_sync_handle:
            self._manager.channel_remove_sync(self._stream, self._loop_sync_handle)
            self._loop_sync_handle = 0
            self._loop_sync_proc = None
        if hasattr(self, "_loop_alt_sync_handle") and self._loop_alt_sync_handle:
            self._manager.channel_remove_sync(self._stream, self._loop_alt_sync_handle)
            self._loop_alt_sync_handle = 0
            self._loop_alt_sync_proc = None
        if hasattr(self, "_loop_end_sync_handle") and self._loop_end_sync_handle:
            self._manager.channel_remove_sync(self._stream, self._loop_end_sync_handle)
            self._loop_end_sync_handle = 0
            self._loop_end_sync_proc = None
        if self._loop_fake_timer:
            self._loop_fake_timer.cancel()
            self._loop_fake_timer = None
        if not self._loop_active or self._loop_end is None or self._loop_start is None:
            return

        start = max(0.0, self._loop_start)
        end = max(start + 0.001, self._loop_end)
        self._loop_start_bytes = self._manager.seconds_to_bytes(self._stream, start)
        self._loop_end_bytes = self._manager.seconds_to_bytes(self._stream, end)
        if self._debug_loop:
            logger.debug(
                "Loop debug: apply loop start=%.6fs end=%.6fs start_bytes=%s end_bytes=%s stream=%s",
                start,
                end,
                self._loop_start_bytes,
                self._loop_end_bytes,
                self._stream,
            )

        # Synci wyłączone – stawiamy na pętlę programową z monitra
        def _sync_cb(handle, channel, data, user):
            try:
                self._last_loop_jump_ts = time.time()
                if self._loop_start_bytes:
                    self._manager.channel_set_position_bytes(self._stream, self._loop_start_bytes)
                else:
                    self._manager.channel_set_position(self._stream, self._loop_start)
                if self._debug_loop:
                    logger.debug(
                        "Loop debug: sync jump handle=%s start=%.6f end=%.6f",
                        handle,
                        self._loop_start,
                        self._loop_end,
                    )
            except Exception as exc:
                if self._debug_loop:
                    logger.debug("Loop debug: sync jump failed: %s", exc)

        try:
            self._loop_sync_proc = self._manager.make_sync_proc(_sync_cb)
            self._loop_sync_handle = self._manager.channel_set_sync_pos(
                self._stream, self._loop_end_bytes, self._loop_sync_proc, is_bytes=True
            )
        except Exception as exc:
            self._loop_sync_proc = None
            self._loop_sync_handle = 0
            if self._debug_loop:
                logger.debug("Loop debug: failed to set sync pos: %s", exc)
        self._loop_alt_sync_proc = None
        self._loop_alt_sync_handle = 0
        self._loop_end_sync_proc = None
        self._loop_end_sync_handle = 0
        if self._debug_loop:
            logger.debug("Loop debug: sync+guard active")


class BassBackend:
    """Adapter providera dla AudioEngine."""

    backend = None  # ustawiane przez AudioEngine po imporcie

    def __init__(self) -> None:
        try:
            self._manager = BassManager.instance()
            self.is_available = True
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("BASS backend niedostępny: %s", exc)
            self.is_available = False
            self._manager = None

    def list_devices(self) -> List["AudioDevice"]:
        if not self.is_available or self._manager is None:
            return []
        try:
            return self._manager.list_devices()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Enumeracja urządzeń BASS nie powiodła się: %s", exc)
            return []

    def create_player(self, device: "AudioDevice") -> BassPlayer:
        if not self.is_available or self._manager is None:
            raise BassNotAvailable("BASS backend niedostępny")
        index = device.raw_index
        if index is None:
            try:
                index = int(str(device.id).split(":")[-1])
            except Exception:
                index = 0
        return BassPlayer(self._manager, index)


class BassAsioBackend:
    """Backend BASS ASIO (bassasio.dll)."""

    backend = None  # ustawiane przez AudioEngine

    def __init__(self) -> None:
        try:
            self._manager = BassManager.instance()
            self.is_available = self._manager._asio is not None
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("BASS ASIO backend niedostępny: %s", exc)
            self.is_available = False
            self._manager = None

    def list_devices(self) -> List["AudioDevice"]:
        if not self.is_available or self._manager is None:
            return []
        try:
            return self._manager.list_asio_devices()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Enumeracja urządzeń BASS ASIO nie powiodła się: %s", exc)
            return []

    def create_player(self, device: "AudioDevice") -> BassAsioPlayer:
        if not self.is_available or self._manager is None:
            raise BassNotAvailable("BASS ASIO backend niedostępny")
        index = device.raw_index
        channel_start = 0
        try:
            parts = str(device.id).split(":")
            if len(parts) >= 3:
                channel_start = int(parts[-1])
        except Exception:
            channel_start = 0
        if index is None:
            try:
                index = int(str(device.id).split(":")[-1])
            except Exception:
                index = 0
        return BassAsioPlayer(self._manager, index, channel_start=channel_start)
        
