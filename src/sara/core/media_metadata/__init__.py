"""Helpers for reading and writing audio metadata.

This package keeps the legacy `sara.core.media_metadata` API stable while
splitting implementation across focused modules.
"""

from __future__ import annotations

from sara.core.media_metadata.constants import (
    CUE_IN_TAG,
    INTRO_TAG,
    LOOP_AUTO_ENABLED_TAG,
    LOOP_ENABLED_TAG,
    LOOP_END_TAG,
    LOOP_START_TAG,
    OUTRO_TAG,
    OVERLAP_TAG,
    REPLAYGAIN_TRACK_GAIN_TAG,
    SEGUE_FADE_TAG,
    SEGUE_TAG,
    SUPPORTED_AUDIO_EXTENSIONS,
)
from sara.core.media_metadata.extract import extract_metadata
from sara.core.media_metadata.models import AudioMetadata
from sara.core.media_metadata.save import save_loop_metadata, save_mix_metadata, save_replay_gain_metadata
from sara.core.media_metadata.support import is_supported_audio_file

__all__ = [
    "AudioMetadata",
    "CUE_IN_TAG",
    "INTRO_TAG",
    "LOOP_AUTO_ENABLED_TAG",
    "LOOP_ENABLED_TAG",
    "LOOP_END_TAG",
    "LOOP_START_TAG",
    "OUTRO_TAG",
    "OVERLAP_TAG",
    "REPLAYGAIN_TRACK_GAIN_TAG",
    "SEGUE_FADE_TAG",
    "SEGUE_TAG",
    "SUPPORTED_AUDIO_EXTENSIONS",
    "extract_metadata",
    "is_supported_audio_file",
    "save_loop_metadata",
    "save_mix_metadata",
    "save_replay_gain_metadata",
]
