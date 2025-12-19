"""Text decoding helpers for BASS device names."""

from __future__ import annotations

import locale
import sys
from typing import Iterable


def _candidate_encodings() -> Iterable[str]:
    yield "utf-8"
    if sys.platform.startswith("win"):
        yield "mbcs"
    preferred = locale.getpreferredencoding(False)
    if preferred:
        yield preferred
    # Common Windows Central European code page (useful for device names with Polish chars).
    yield "cp1250"


def decode_bass_text(raw: bytes | str | None) -> str:
    """Decode BASS-provided byte strings without losing non-ASCII characters."""

    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw

    tried: set[str] = set()
    for encoding in _candidate_encodings():
        if not encoding:
            continue
        key = encoding.lower()
        if key in tried:
            continue
        tried.add(key)
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue

    return raw.decode("utf-8", errors="replace")


__all__ = [
    "decode_bass_text",
]

