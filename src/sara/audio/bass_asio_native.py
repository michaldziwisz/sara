"""Low-level BASS ASIO (bassasio) loader and ctypes prototypes."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import List

from sara.audio.bass_native import BassNotAvailable


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
                        return (
                            ctypes.WinDLL(str(candidate))
                            if sys.platform.startswith("win")
                            else ctypes.CDLL(str(candidate))
                        )
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

