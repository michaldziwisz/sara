"""Helpers for announcing messages to screen readers like NVDA."""

from __future__ import annotations

import logging
import os
import struct
import sys
import threading
from pathlib import Path
from typing import Iterable, Optional

try:  # pragma: no cover - defensive import, covered through helper logic
    import ctypes
except Exception:  # pragma: no cover - CTYPES is part of stdlib but be safe
    ctypes = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


def _is_windows() -> bool:
    return sys.platform.startswith("win")


class _NvdaClient:
    """Thin wrapper over NVDA controller DLL (on Windows only)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._controller: Optional["ctypes._SimpleCData"] = None  # type: ignore[attr-defined]
        self._load_failed = False

    def speak(self, message: str) -> bool:
        if not message:
            return False
        controller = self._ensure_loaded()
        if controller is None:
            return False
        try:
            result = controller.nvdaController_speakText(ctypes.c_wchar_p(message))  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - NVDA specific path
            logger.debug("NVDA speak failed: %s", exc)
            return False
        return result == 0

    def cancel(self) -> bool:
        controller = self._ensure_loaded()
        if controller is None:
            return False
        cancel_func = getattr(controller, "nvdaController_cancelSpeech", None)
        if cancel_func is None:
            return False
        try:
            result = cancel_func()
        except Exception as exc:  # pragma: no cover - NVDA specific path
            logger.debug("NVDA cancel speech failed: %s", exc)
            return False
        return result == 0

    def reset(self) -> None:
        with self._lock:
            self._controller = None
            self._load_failed = False

    def _ensure_loaded(self):
        with self._lock:
            if self._controller is not None:
                return self._controller
            if self._load_failed:
                return None

            if not _is_windows():
                self._load_failed = True
                return None
            if ctypes is None:
                self._load_failed = True
                return None

            loader = getattr(ctypes, "WinDLL", None)
            if loader is None:  # pragma: no cover - Unix Python
                self._load_failed = True
                return None

            for candidate in self._candidate_dlls():
                dll_path = str(candidate)
                try:
                    controller = loader(dll_path)
                    controller.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]  # type: ignore[attr-defined]
                    controller.nvdaController_speakText.restype = ctypes.c_int  # type: ignore[attr-defined]
                    cancel_func = getattr(controller, "nvdaController_cancelSpeech", None)
                    if cancel_func is not None:
                        cancel_func.argtypes = []  # type: ignore[attr-defined]
                        cancel_func.restype = ctypes.c_int  # type: ignore[attr-defined]
                    self._controller = controller
                    return controller
                except OSError:
                    continue
                except Exception as exc:  # pragma: no cover - unexpected failure
                    logger.debug("NVDA controller init failed: %s", exc)
                    break

            self._load_failed = True
            return None

    @staticmethod
    def _candidate_names() -> list[str]:
        if struct.calcsize("P") * 8 == 64:
            return ["nvdaControllerClient64.dll", "nvdaControllerClient.dll"]
        return ["nvdaControllerClient32.dll", "nvdaControllerClient.dll"]

    @classmethod
    def _candidate_dlls(cls) -> Iterable[Path]:
        names = cls._candidate_names()

        env_value = os.environ.get("NVDA_CONTROLLER_DLL")
        if env_value:
            for entry in env_value.split(os.pathsep):
                path = Path(entry)
                if path.is_dir():
                    for name in names:
                        yield path / name
                else:
                    yield path

        base_dir = Path(__file__).resolve().parent
        for name in names:
            candidate = base_dir / name
            if candidate.exists():
                yield candidate

        exe_dir = _executable_dir()
        if exe_dir:
            for name in names:
                candidate = exe_dir / name
                if candidate.exists():
                    yield candidate

        program_files_keys = ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)")
        for env_key in program_files_keys:
            base = os.environ.get(env_key)
            if not base:
                continue
            base_path = Path(base)
            for subdir in ("NVDA", "nvda"):
                folder = base_path / subdir
                if not folder.exists():
                    continue
                for name in names:
                    yield folder / name

        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            portable_dir = Path(local_app) / "NVDA"
            if portable_dir.exists():
                for name in names:
                    yield portable_dir / name


_NVDA_CLIENT = _NvdaClient()


def speak_text(message: str) -> bool:
    """Announce `message` through NVDA if available.

    Returns True when NVDA accepted the text, False otherwise.
    """

    return _NVDA_CLIENT.speak(message)


def cancel_speech() -> bool:
    """Cancel any ongoing NVDA speech output if the API is available."""

    return _NVDA_CLIENT.cancel()


__all__ = ["speak_text", "cancel_speech"]
def _executable_dir() -> Optional[Path]:
    """Return directory of frozen executable when running from PyInstaller."""

    if getattr(sys, "frozen", False):  # type: ignore[attr-defined]
        try:
            return Path(sys.executable).resolve().parent
        except Exception:  # pragma: no cover - fallback only
            return None
    return None
