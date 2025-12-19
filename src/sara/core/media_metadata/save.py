"""Persist mix-related metadata in APE tags."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from mutagen import File as MutagenFile
from mutagen.apev2 import APEv2, error as APEv2Error

from sara.core.media_metadata.ape import _read_ape_tags
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
)


logger = logging.getLogger(__name__)


def save_loop_metadata(
    path: Path,
    start: Optional[float],
    end: Optional[float],
    enabled: Optional[bool] = None,
    auto_enabled: Optional[bool] = None,
) -> bool:
    """Save or remove loop markers in APEv2 tags.

    Returns True if the operation succeeded, False otherwise.
    """

    file_path = str(path)
    tags: APEv2 | None = None
    existing = False

    try:
        audio = MutagenFile(file_path)
    except Exception:  # pylint: disable=broad-except
        audio = None

    if audio is not None and isinstance(getattr(audio, "tags", None), APEv2):
        tags = audio.tags  # type: ignore[assignment]
        existing = True

    if tags is None:
        try:
            tags = APEv2(file_path)
            existing = True
        except APEv2Error:
            tags = APEv2()
            existing_items = _read_ape_tags(path)
            for key, value in existing_items.items():
                if key in (LOOP_START_TAG, LOOP_END_TAG, LOOP_ENABLED_TAG, LOOP_AUTO_ENABLED_TAG):
                    continue
                tags[key] = value

    if tags is None:
        logger.warning("Unable to initialise APE tags for %s", path)
        return False

    try:
        if start is None or end is None:
            removed = False
            for key in (LOOP_START_TAG, LOOP_END_TAG, LOOP_ENABLED_TAG, LOOP_AUTO_ENABLED_TAG):
                if key in tags:
                    removed = True
                    try:
                        tags.pop(key)
                    except KeyError:
                        pass
            if removed or existing:
                tags.save(file_path)
            return True

        if end <= start:
            logger.warning("Ignoring loop save – invalid values (%s, %s)", start, end)
            return False

        tags[LOOP_START_TAG] = f"{start:.3f}"
        tags[LOOP_END_TAG] = f"{end:.3f}"
        if enabled is not None:
            tags[LOOP_ENABLED_TAG] = "1" if enabled else "0"
        if auto_enabled is not None:
            tags[LOOP_AUTO_ENABLED_TAG] = "1" if auto_enabled else "0"
        tags.save(file_path)
        return True
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Failed to update loop tags for %s: %s", path, exc)
        return False


def save_mix_metadata(
    path: Path,
    *,
    cue_in: Optional[float],
    intro: Optional[float],
    outro: Optional[float],
    segue: Optional[float],
    segue_fade: Optional[float],
    overlap: Optional[float],
) -> bool:
    """Persist cue/intro/outro/segue/segue_fade/overlap markers in APEv2 tags."""

    file_path = str(path)
    tags: APEv2 | None = None
    existing = False

    try:
        audio = MutagenFile(file_path)
    except Exception:  # pylint: disable=broad-except
        audio = None

    if audio is not None and isinstance(getattr(audio, "tags", None), APEv2):
        tags = audio.tags  # type: ignore[assignment]
        existing = True

    mix_keys = {
        CUE_IN_TAG,
        INTRO_TAG,
        OUTRO_TAG,
        SEGUE_TAG,
        SEGUE_FADE_TAG,
        OVERLAP_TAG,
    }

    if tags is None:
        try:
            tags = APEv2(file_path)
            existing = True
        except APEv2Error:
            tags = APEv2()
            existing_items = _read_ape_tags(path)
            for key, value in existing_items.items():
                if key in mix_keys:
                    continue
                tags[key] = value

    if tags is None:
        logger.warning("Unable to initialise APE tags for %s", path)
        return False

    updates = {
        CUE_IN_TAG: cue_in,
        INTRO_TAG: intro,
        OUTRO_TAG: outro,
        SEGUE_TAG: segue,
        SEGUE_FADE_TAG: segue_fade,
        OVERLAP_TAG: overlap,
    }

    try:
        modified = False
        for key, value in updates.items():
            if value is None:
                if key in tags:
                    try:
                        tags.pop(key)
                    except KeyError:
                        pass
                    modified = True
                continue
            tags[key] = f"{value:.3f}"
            modified = True
        if modified or existing:
            tags.save(file_path)
        return True
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Failed to update mix tags for %s: %s", path, exc)
        return False


def save_replay_gain_metadata(path: Path, gain_db: Optional[float]) -> bool:
    """Persist ReplayGain track gain (compatible with SPL) in APE tags."""

    file_path = str(path)
    tags: APEv2 | None = None
    existing = False

    try:
        audio = MutagenFile(file_path)
    except Exception:  # pylint: disable=broad-except
        audio = None

    if audio is not None and isinstance(getattr(audio, "tags", None), APEv2):
        tags = audio.tags  # type: ignore[assignment]
        existing = True

    if tags is None:
        try:
            tags = APEv2(file_path)
            existing = True
        except APEv2Error:
            tags = APEv2()
            existing_items = _read_ape_tags(path)
            for key, value in existing_items.items():
                if key == REPLAYGAIN_TRACK_GAIN_TAG:
                    continue
                tags[key] = value

    if tags is None:
        logger.warning("Unable to initialise APE tags for %s", path)
        return False

    try:
        modified = False
        if gain_db is None:
            if REPLAYGAIN_TRACK_GAIN_TAG in tags:
                try:
                    tags.pop(REPLAYGAIN_TRACK_GAIN_TAG)
                except KeyError:
                    pass
                modified = True
        else:
            tags[REPLAYGAIN_TRACK_GAIN_TAG] = f"{gain_db:+.2f} dB"
            modified = True
        if modified or existing:
            tags.save(file_path)
        return True
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Failed to update ReplayGain tags for %s: %s", path, exc)
        return False

