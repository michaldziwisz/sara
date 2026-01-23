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
import threading
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


class RustCallbackExecutor:
    """Execute arbitrary Python callbacks on a Rust worker thread.

    Used for PFL mix preview/testing where we want the callback to run off the
    BASS sync thread but still keep the worker thread in native code.
    """

    def __init__(self) -> None:
        self._lib, self._lib_path = _load_library()

        create = getattr(self._lib, "sara_mix_executor_create", None)
        enqueue = getattr(self._lib, "sara_mix_executor_enqueue", None)
        destroy = getattr(self._lib, "sara_mix_executor_destroy", None)
        if not (create and enqueue and destroy):
            raise RuntimeError("Rust callback executor: missing required symbols")

        create.argtypes = [_CALLBACK]
        create.restype = ctypes.c_void_p
        enqueue.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        enqueue.restype = None
        destroy.argtypes = [ctypes.c_void_p]
        destroy.restype = None

        self._enqueue = enqueue
        self._destroy = destroy
        self._lock = threading.Lock()
        self._pending: dict[str, callable] = {}
        self._counter = 0

        self._callback = _CALLBACK(self._on_task)
        self._handle = create(self._callback)
        if not self._handle:
            raise RuntimeError("Rust callback executor: failed to create executor")

        if self._lib_path:
            logger.info("Rust callback executor loaded: %s", self._lib_path)
        else:
            logger.info("Rust callback executor loaded via system loader")

    def submit(self, func) -> str | None:
        handle = getattr(self, "_handle", None)
        if not handle or not callable(func):
            return None
        with self._lock:
            self._counter += 1
            token = f"task-{self._counter}"
            self._pending[token] = func
        try:
            self._enqueue(handle, token.encode("utf-8", errors="replace"), b"")
        except Exception:
            with self._lock:
                self._pending.pop(token, None)
            logger.exception("RUST: submit failed token=%s", token)
            return None
        return token

    def clear(self) -> None:
        with self._lock:
            self._pending.clear()

    def shutdown(self) -> None:
        handle = getattr(self, "_handle", None)
        if not handle:
            return
        try:
            self._destroy(handle)
        except Exception:
            logger.exception("RUST: callback executor shutdown failed")
        finally:
            self._handle = None
            self.clear()

    def _on_task(self, playlist_id: bytes | None, _item_id: bytes | None) -> None:
        token = (playlist_id or b"").decode("utf-8", errors="replace")
        func = None
        with self._lock:
            func = self._pending.pop(token, None)
        if not func:
            return
        try:
            func()
        except Exception:
            logger.exception("RUST: callback task failed token=%s", token)
