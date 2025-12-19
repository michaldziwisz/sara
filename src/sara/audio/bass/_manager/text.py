"""Text decoding helpers for BASS device names."""

from __future__ import annotations

import locale
import sys
from typing import Iterable


_POLISH_CHARS = frozenset("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


def _candidate_encodings() -> Iterable[str]:
    yield "utf-8"
    if sys.platform.startswith("win"):
        yield "mbcs"
    preferred = locale.getpreferredencoding(False)
    if preferred:
        yield preferred
    # Common Windows Central European code page (useful for device names with Polish chars).
    yield "cp1250"


def _score_decoded_text(text: str) -> tuple[int, int, int]:
    polish = sum(ch in _POLISH_CHARS for ch in text)
    alpha = sum(ch.isalpha() for ch in text)
    # Likely mojibake when decoding CP1250 bytes with Western Windows code pages.
    mojibake = sum(ch in "£³¹¿" for ch in text)
    return (polish, alpha, -mojibake)


def decode_bass_text(raw: bytes | str | None) -> str:
    """Decode BASS-provided byte strings without losing non-ASCII characters."""

    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw

    is_windows = sys.platform.startswith("win")
    windows_candidates: list[str] = []
    tried: set[str] = set()
    for encoding in _candidate_encodings():
        if not encoding:
            continue
        key = encoding.lower()
        if key in tried:
            continue
        tried.add(key)
        try:
            decoded = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if key == "utf-8":
            return decoded
        if is_windows:
            windows_candidates.append(decoded)
        else:
            return decoded

    if windows_candidates:
        return max(windows_candidates, key=_score_decoded_text)

    return raw.decode("utf-8", errors="replace")


__all__ = [
    "decode_bass_text",
]
