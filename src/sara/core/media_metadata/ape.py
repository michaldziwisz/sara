"""APE tag scanning helpers."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Optional

from sara.core.media_metadata.constants import (
    LOOP_AUTO_ENABLED_TAG,
    LOOP_ENABLED_TAG,
    LOOP_END_TAG,
    LOOP_START_TAG,
)


def _read_ape_tags(path: Path) -> dict[str, str]:
    try:
        data = path.read_bytes()
    except OSError:
        return {}
    marker = b"APETAGEX"
    idx = data.rfind(marker)
    if idx == -1 or idx + 32 > len(data):
        return {}
    magic, version, size, count, flags, reserved = struct.unpack("<8sIIIIQ", data[idx : idx + 32])
    if size <= 32 or count <= 0:
        return {}
    start = idx - (size - 32)
    if start < 0 or start >= len(data):
        return {}
    items = data[start:idx]
    pos = 0
    tags: dict[str, str] = {}
    for _ in range(count):
        if pos + 8 > len(items):
            break
        value_size, item_flags = struct.unpack_from("<II", items, pos)
        pos += 8
        end_key = items.find(b"\x00", pos)
        if end_key == -1:
            break
        key = items[pos:end_key].decode("utf-8", errors="ignore")
        pos = end_key + 1
        value_bytes = items[pos : pos + value_size]
        pos += value_size
        value = value_bytes.rstrip(b"\x00").decode("utf-8", errors="ignore")
        tags[key] = value.strip()
    return tags


def _scan_ape_value(path: Path, key: str) -> Optional[str]:
    tags = _read_ape_tags(path)
    if not tags:
        return None
    for lookup in (key, key.upper(), key.lower()):
        if lookup in tags:
            value = tags[lookup].strip()
            return value if value else None
    return None


def _scan_ape_replay_gain(path: Path) -> Optional[float]:
    for key in ("REPLAYGAIN_TRACK_GAIN", "replaygain_track_gain"):
        text = _scan_ape_value(path, key)
        if not text:
            continue
        text = text.replace(",", ".")
        if text.lower().endswith("db"):
            text = text[:-2].strip()
        for token in text.split():
            try:
                return float(token)
            except ValueError:
                continue
    return None


def _scan_loop_values(path: Path) -> tuple[Optional[float], Optional[float], bool, bool]:
    tags = _read_ape_tags(path)
    if not tags:
        return None, None, False, False

    def _lookup(key: str) -> Optional[str]:
        for variant in (key, key.upper(), key.lower()):
            if variant in tags:
                value = tags[variant].strip()
                return value if value else None
        return None

    def _to_float(value: Optional[str]) -> Optional[float]:
        if not value:
            return None
        try:
            return float(value.replace(",", "."))
        except (ValueError, AttributeError):
            return None

    start = _to_float(_lookup(LOOP_START_TAG))
    end = _to_float(_lookup(LOOP_END_TAG))
    enabled_text = _lookup(LOOP_ENABLED_TAG)
    enabled = False
    if enabled_text is not None:
        enabled = enabled_text.strip().lower() in ("1", "true", "yes", "on")
    auto_text = _lookup(LOOP_AUTO_ENABLED_TAG)
    auto_enabled = False
    if auto_text is not None:
        auto_enabled = auto_text.strip().lower() in ("1", "true", "yes", "on")

    if start is None or end is None or end <= start:
        return None, None, False, auto_enabled

    return start, end, enabled, auto_enabled

