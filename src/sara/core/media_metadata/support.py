"""Helpers for file support checks."""

from __future__ import annotations

from pathlib import Path

from sara.core.media_metadata.constants import SUPPORTED_AUDIO_EXTENSIONS


def is_supported_audio_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS

