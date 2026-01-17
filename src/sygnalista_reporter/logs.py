from __future__ import annotations

import base64
import gzip
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PreparedLog:
    file_name: str
    original_bytes: int
    truncated: bool
    gz_base64: str


def _tail_bytes(path: str, tail_bytes: int) -> bytes:
    with open(path, "rb") as f:
        if tail_bytes <= 0:
            return b""
        f.seek(-tail_bytes, os.SEEK_END)
        return f.read()


def _gzip_base64(data: bytes) -> str:
    return base64.b64encode(gzip.compress(data)).decode("ascii")


def prepare_log_file(
    path: str,
    *,
    max_full_bytes: int = 20_000_000,
    max_tail_bytes: int = 5_000_000,
    max_gz_base64_length: int = 8_000_000,
) -> PreparedLog | None:
    if not path:
        return None
    if not os.path.exists(path):
        return None
    if not os.path.isfile(path):
        return None

    original_size = os.path.getsize(path)
    file_name = os.path.basename(path) + ".gz"

    if original_size <= max_full_bytes:
        with open(path, "rb") as f:
            full = f.read()
        gz_b64 = _gzip_base64(full)
        if len(gz_b64) <= max_gz_base64_length:
            return PreparedLog(
                file_name=file_name,
                original_bytes=original_size,
                truncated=False,
                gz_base64=gz_b64,
            )

    tail_size = min(max_tail_bytes, original_size)
    min_tail_size = min(200_000, tail_size)
    while tail_size >= min_tail_size:
        tail = _tail_bytes(path, tail_bytes=tail_size)
        gz_b64 = _gzip_base64(tail)
        if len(gz_b64) <= max_gz_base64_length or tail_size == min_tail_size:
            return PreparedLog(
                file_name=file_name,
                original_bytes=original_size,
                truncated=(original_size > tail_size),
                gz_base64=gz_b64,
            )
        tail_size = max(min_tail_size, tail_size // 2)

    return None

