"""Rust-based executor for native mix triggers (experimental).

This executor offloads the mix-trigger queue + worker thread to a small Rust DLL.
The heavy mix logic still runs in Python (on the Rust worker thread) to keep the
change surface minimal while allowing real-world timing/jitter measurements.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path


logger = logging.getLogger(__name__)

_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_char_p)


def _possible_library_names() -> list[str]:
    if sys.platform.startswith("win"):
        return ["sara_mix_executor.dll"]
    if sys.platform == "darwin":
        return ["libsara_mix_executor.dylib", "sara_mix_executor.dylib"]
    return ["libsara_mix_executor.so", "sara_mix_executor.so"]


def _load_library() -> tuple[ctypes.CDLL, Path | None]:
    names = _possible_library_names()
    search_paths: list[Path] = []

    env_path = os.environ.get("SARA_MIX_EXECUTOR_LIBRARY_PATH")
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.is_file():
            return ctypes.CDLL(str(candidate)), candidate
        if candidate.is_dir():
            search_paths.append(candidate)

    module_dir = Path(__file__).resolve().parent
    search_paths.append(Path.cwd())
    search_paths.append(module_dir)
    search_paths.append(module_dir.parent)

    if getattr(sys, "frozen", False):  # pragma: no cover - only in packaged app
        try:
            search_paths.append(Path(sys.executable).resolve().parent)
        except Exception:
            pass
        try:
            meipass = Path(getattr(sys, "_MEIPASS"))
            search_paths.append(meipass)
            search_paths.append(meipass / "sara")
        except Exception:
            pass

    for directory in search_paths:
        for name in names:
            candidate = directory / name
            if candidate.exists():
                return ctypes.CDLL(str(candidate)), candidate

    # Fall back to system loader / PATH.
    last_error: Exception | None = None
    for name in names:
        try:
            return ctypes.CDLL(name), None
        except OSError as exc:
            last_error = exc
    raise FileNotFoundError("Rust mix executor library not found") from last_error


class RustMixExecutor:
    """Native worker thread implemented in Rust calling back into Python."""

    def __init__(self, frame) -> None:
        self._frame = frame
        self._lib, self._lib_path = _load_library()

        create = getattr(self._lib, "sara_mix_executor_create", None)
        enqueue = getattr(self._lib, "sara_mix_executor_enqueue", None)
        destroy = getattr(self._lib, "sara_mix_executor_destroy", None)
        if not (create and enqueue and destroy):
            raise RuntimeError("Rust mix executor: missing required symbols")

        self._callback = _CALLBACK(self._on_work_item)

        create.argtypes = [_CALLBACK]
        create.restype = ctypes.c_void_p
        enqueue.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        enqueue.restype = None
        destroy.argtypes = [ctypes.c_void_p]
        destroy.restype = None

        self._create = create
        self._enqueue = enqueue
        self._destroy = destroy

        self._handle = self._create(self._callback)
        if not self._handle:
            raise RuntimeError("Rust mix executor: failed to create executor")

        if self._lib_path:
            logger.info("Rust mix executor loaded: %s", self._lib_path)
        else:
            logger.info("Rust mix executor loaded via system loader")

    def enqueue(self, playlist_id: str, item_id: str) -> None:
        handle = getattr(self, "_handle", None)
        if not handle:
            return
        try:
            self._enqueue(
                handle,
                str(playlist_id).encode("utf-8", errors="replace"),
                str(item_id).encode("utf-8", errors="replace"),
            )
        except Exception:
            logger.exception("RUST: enqueue failed playlist=%s item=%s", playlist_id, item_id)

    def shutdown(self, *, timeout: float = 1.0) -> None:  # timeout kept for API parity
        _ = timeout
        handle = getattr(self, "_handle", None)
        if not handle:
            return
        try:
            self._destroy(handle)
        except Exception:
            logger.exception("RUST: shutdown failed")
        finally:
            self._handle = None

    def _on_work_item(self, playlist_id: bytes | None, item_id: bytes | None) -> None:
        try:
            pl_id = (playlist_id or b"").decode("utf-8", errors="replace")
            it_id = (item_id or b"").decode("utf-8", errors="replace")

            from sara.ui.mix_runtime.thread_executor import handle_native_mix_trigger

            handle_native_mix_trigger(
                self._frame,
                playlist_id=pl_id,
                item_id=it_id,
                enqueue_mix_trigger=self.enqueue,
                executor_name="rust",
            )
        except Exception:
            logger.exception("RUST: unhandled error while processing mix trigger")

