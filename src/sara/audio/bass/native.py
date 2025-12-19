"""Low-level BASS library loader and ctypes prototypes.

This module contains the minimal pieces needed to load the native BASS library
without pulling higher-level player/engine code into the same file.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


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
        audio_dir = Path(__file__).resolve().parents[1]
        search_paths.append(Path.cwd())
        search_paths.append(audio_dir)
        search_paths.append(audio_dir / "vendor")
        platform_dir = audio_dir / "vendor" / ("windows" if sys.platform.startswith("win") else "linux")
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
                        return (
                            ctypes.WinDLL(str(candidate))
                            if sys.platform.startswith("win")
                            else ctypes.CDLL(str(candidate))
                        )
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
