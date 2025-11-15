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

if TYPE_CHECKING:  # pragma: no cover
    from sara.audio.engine import AudioDevice


class BassNotAvailable(Exception):
    """Wyrzucane, gdy biblioteki BASS nie udało się załadować."""


class _BassConstants:
    DEVICE_ENABLED = 0x0001
    DEVICE_DEFAULT = 0x0002

    SAMPLE_FLOAT = 0x10000
    STREAM_PRESCAN = 0x20000

    POS_BYTE = 0
    ATTRIB_VOL = 2

    ACTIVE_STOPPED = 0
    SYNC_POS = 0x00000010
    SYNC_MIXTIME = 0x40000000


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
        for directory in search_paths:
            for name in names:
                candidate = directory / name
                if candidate.exists():
                    try:
                        return ctypes.WinDLL(str(candidate)) if sys.platform.startswith("win") else ctypes.CDLL(str(candidate))
                    except OSError as exc:  # pragma: no cover - zależne od środowiska
                        errors.append(f"{candidate}: {exc}")
        for name in names:
            try:
                return ctypes.WinDLL(name) if sys.platform.startswith("win") else ctypes.CDLL(name)
            except OSError as exc:  # pragma: no cover - zależne od środowiska
                errors.append(f"{name}: {exc}")
        raise BassNotAvailable("Nie znaleziono biblioteki BASS (ustaw zmienną BASS_LIBRARY_PATH)")

    def _configure_prototypes(self) -> None:
        lib = self._lib
        DWORD = ctypes.c_uint
        QWORD = ctypes.c_ulonglong
        BOOL = ctypes.c_bool

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


class _DeviceContext:
    def __init__(self, manager: "BassManager", index: int):
        self._manager = manager
        self.index = index

    def release(self) -> None:
        self._manager._release_device(self.index)


class BassManager:
    """Singleton zarządzający dostępem do BASS."""

    _instance_lock = threading.Lock()
    _instance: Optional["BassManager"] = None

    def __init__(self) -> None:
        lib_wrapper = _BassLibrary()
        self._lib = lib_wrapper.handle
        self._sync_type = lib_wrapper.sync_proc_type
        self._devices: dict[int, dict[str, Any]] = {}
        self._global_lock = threading.Lock()
        # skróć opóźnienie aktualizacji, żeby pętle reagowały szybko
        self._lib.BASS_SetConfig(0x10500, 5)  # BASS_CONFIG_UPDATEPERIOD
        self._lib.BASS_SetConfig(0x10504, 2)  # BASS_CONFIG_UPDATETHREADS

    @classmethod
    def instance(cls) -> "BassManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    def list_devices(self) -> List["AudioDevice"]:
        from sara.audio.engine import AudioDevice, BackendType

        devices: List[AudioDevice] = []
        index = 0
        info = _BASS_DEVICEINFO()
        while self._lib.BASS_GetDeviceInfo(index, ctypes.byref(info)):
            flags = info.flags
            enabled = bool(flags & _BassConstants.DEVICE_ENABLED)
            name_bytes = info.name or b""
            name = name_bytes.decode("utf-8", errors="ignore") if name_bytes else f"Device {index}"
            if enabled:
                devices.append(
                    AudioDevice(
                        id=f"bass:{index}",
                        name=name,
                        backend=BackendType.BASS,
                        raw_index=index,
                        is_default=bool(flags & _BassConstants.DEVICE_DEFAULT),
                    )
                )
            index += 1
        return devices

    def acquire_device(self, index: int) -> _DeviceContext:
        with self._global_lock:
            data = self._devices.setdefault(index, {"ref": 0, "init": False})
            if not data["init"]:
                success = self._lib.BASS_Init(index, 44100, 0, None, None)
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

    def ensure_device(self, index: int) -> None:
        self.acquire_device(index).release()

    def _set_device(self, index: int) -> None:
        if not self._lib.BASS_SetDevice(index):
            code = self._lib.BASS_ErrorGetCode()
            raise BassNotAvailable(f"BASS_SetDevice({index}) nie powiodło się (kod {code})")

    def stream_create_file(self, index: int, path: Path) -> int:
        self._set_device(index)
        flags = _BassConstants.SAMPLE_FLOAT | _BassConstants.STREAM_PRESCAN
        path_bytes = str(path).encode("utf-8")
        stream = self._lib.BASS_StreamCreateFile(False, path_bytes, 0, 0, flags)
        if not stream:
            code = self._lib.BASS_ErrorGetCode()
            raise BassNotAvailable(f"BASS_StreamCreateFile nie powiodło się (kod {code})")
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

    def channel_set_volume(self, stream: int, volume: float) -> None:
        volume = max(0.0, min(volume, 1.0))
        self._lib.BASS_ChannelSetAttribute(stream, _BassConstants.ATTRIB_VOL, ctypes.c_float(volume))

    def seconds_to_bytes(self, stream: int, seconds: float) -> int:
        return int(self._lib.BASS_ChannelSeconds2Bytes(stream, ctypes.c_double(seconds)))

    def channel_set_position_bytes(self, stream: int, byte_pos: int) -> None:
        self._lib.BASS_ChannelSetPosition(stream, byte_pos, _BassConstants.POS_BYTE)

    def make_sync_proc(self, func: Callable[[int, int, int, ctypes.c_void_p], None]):
        return self._sync_type(func)

    def channel_set_sync_pos(self, stream: int, seconds: float, proc) -> int:
        position = self.seconds_to_bytes(stream, seconds)
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


class BassPlayer:
    """Implementacja Player korzystająca z BASS."""

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
        self._finished_callback: Optional[Callable[[str], None]] = None
        self._progress_callback: Optional[Callable[[str, float], None]] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_stop = threading.Event()
        self._fade_thread: Optional[threading.Thread] = None

    # --- lifecycle ---
    def play(self, playlist_item_id: str, source_path: str, *, start_seconds: float = 0.0) -> Optional[threading.Event]:
        self.stop()
        self._current_item_id = playlist_item_id
        path = Path(source_path)
        self._device_context = self._manager.acquire_device(self._device_index)
        self._stream = self._manager.stream_create_file(self._device_index, path)
        if start_seconds > 0:
            self._manager.channel_set_position(self._stream, start_seconds)
        self._apply_gain()
        self._manager.channel_play(self._stream, False)
        self._loop_active = bool(self._loop_start is not None and self._loop_end is not None)
        self._apply_loop_settings()
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
            self._manager.channel_stop(self._stream)
            if self._loop_sync_handle:
                self._manager.channel_remove_sync(self._stream, self._loop_sync_handle)
                self._loop_sync_handle = 0
                self._loop_sync_proc = None
            self._manager.stream_free(self._stream)
            self._stream = 0
        if self._device_context:
            self._device_context.release()
            self._device_context = None
        self._current_item_id = None
        self._loop_active = False
        if self._monitor_thread and self._monitor_thread.is_alive() and not _from_fade:
            self._monitor_thread.join(timeout=0.5)
        self._monitor_thread = None
        self._monitor_stop.clear()
        if _from_fade:
            self._fade_thread = None

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

    def set_loop(self, start_seconds: Optional[float], end_seconds: Optional[float]) -> None:
        if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
            self._loop_start = None
            self._loop_end = None
            self._loop_active = False
            if self._loop_sync_handle and self._stream:
                self._manager.channel_remove_sync(self._stream, self._loop_sync_handle)
            self._loop_sync_handle = 0
            self._loop_sync_proc = None
            return
        self._loop_start = start_seconds
        self._loop_end = end_seconds
        self._loop_active = True
        self._apply_loop_settings()

    def _apply_loop_settings(self) -> None:
        if not self._stream:
            return
        if self._loop_sync_handle:
            self._manager.channel_remove_sync(self._stream, self._loop_sync_handle)
            self._loop_sync_handle = 0
            self._loop_sync_proc = None
        if not self._loop_active or self._loop_end is None or self._loop_start is None:
            return

        start = max(0.0, self._loop_start)
        end = max(start + 0.001, self._loop_end)

        def _sync_proc(hsync, channel, data, user):  # pragma: no cover - C callback
            try:
                self._manager.channel_set_position(channel, start)
            except Exception as exc:
                logger.warning("BASS: nie udało się ustawić pozycji pętli: %s", exc)

        self._loop_sync_proc = self._manager.make_sync_proc(_sync_proc)
        try:
            self._loop_sync_handle = self._manager.channel_set_sync_pos(self._stream, end, self._loop_sync_proc)
        except Exception as exc:
            logger.warning("BASS: nie udało się zarejestrować pętli: %s", exc)
            self._loop_sync_proc = None
            self._loop_sync_handle = 0

    # --- monitorowanie ---
    def _start_monitor(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        def _monitor() -> None:
            try:
                while not self._monitor_stop.is_set() and self._stream:
                    time.sleep(0.05)
                    stream = self._stream
                    if not stream:
                        break
                    seconds = self._manager.channel_get_seconds(stream)
                    item_id = self._current_item_id
                    if item_id and self._progress_callback:
                        self._progress_callback(item_id, seconds)
                    if not self._manager.channel_is_active(stream):
                        if item_id and self._finished_callback:
                            self._finished_callback(item_id)
                        break
            finally:
                self._monitor_stop.clear()

        self._monitor_thread = threading.Thread(target=_monitor, daemon=True)
        self._monitor_thread.start()


class BassBackend:
    """Provider BASS dla AudioEngine."""

    def __init__(self) -> None:
        try:
            self._manager = BassManager.instance()
            self.is_available = True
        except BassNotAvailable as exc:
            logger.info("BASS niedostępny: %s", exc)
            self._manager = None
            self.is_available = False
        self.backend = None

    def list_devices(self) -> List["AudioDevice"]:
        if not self.is_available or self._manager is None:
            return []
        return self._manager.list_devices()

    def create_player(self, device: "AudioDevice") -> BassPlayer:
        if not self.is_available or self._manager is None:
            raise RuntimeError("BASS backend jest niedostępny")
        if self.backend is None:
            from sara.audio.engine import BackendType

            self.backend = BackendType.BASS
        if not device.raw_index and device.raw_index != 0:
            raise ValueError("Oczekiwano indeksu urządzenia BASS")
        return BassPlayer(self._manager, int(device.raw_index))
