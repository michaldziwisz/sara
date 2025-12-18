"""Metadata extraction helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from mutagen import File as MutagenFile

from sara.core.media_metadata.ape import _scan_ape_replay_gain, _scan_ape_value, _scan_loop_values
from sara.core.media_metadata.constants import (
    CUE_IN_TAG,
    INTRO_TAG,
    OUTRO_TAG,
    OVERLAP_TAG,
    SEGUE_FADE_TAG,
    SEGUE_TAG,
)
from sara.core.media_metadata.models import AudioMetadata


logger = logging.getLogger(__name__)


def _parse_replay_gain(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        cleaned = value.strip()
        if cleaned.endswith(" dB"):
            cleaned = cleaned[:-3]
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def extract_metadata(path: Path) -> AudioMetadata:
    """Return track metadata (title, duration, ReplayGain in dB).

    If reading metadata fails, fall back to the file name and duration 0.
    """

    title = path.stem
    duration = 0.0
    replay_gain: Optional[float] = None
    artist: Optional[str] = None

    audio = None
    try:
        audio = MutagenFile(path)
        if audio is None:
            return AudioMetadata(
                title=title,
                duration_seconds=duration,
                artist=artist,
                replay_gain_db=_scan_ape_replay_gain(path),
                outro_seconds=None,
            )
        if audio.tags:
            title_tag = audio.tags.get("TIT2") or audio.tags.get("title")
            if title_tag:
                # mutagen może zwracać obiekty z metodą text lub str
                if hasattr(title_tag, "text"):
                    text = title_tag.text
                    if isinstance(text, (list, tuple)) and text:
                        title = str(text[0])
                    elif isinstance(text, str):
                        title = text
                else:
                    title = str(title_tag)

            artist_tag = audio.tags.get("TPE1") or audio.tags.get("artist")
            if artist_tag:
                if hasattr(artist_tag, "text"):
                    text = artist_tag.text
                    if isinstance(text, (list, tuple)) and text:
                        artist = str(text[0])
                    elif isinstance(text, str):
                        artist = text
                else:
                    artist = str(artist_tag)

            gain_sources = [
                audio.tags.get("REPLAYGAIN_TRACK_GAIN"),
                audio.tags.get("replaygain_track_gain"),
                audio.tags.get("TXXX:replaygain_track_gain"),
            ]
            for gain_tag in gain_sources:
                if gain_tag is None:
                    continue
                if hasattr(gain_tag, "text"):
                    text = gain_tag.text
                    value = text[0] if isinstance(text, (list, tuple)) and text else text
                else:
                    value = str(gain_tag)
                replay_gain = _parse_replay_gain(str(value))
                if replay_gain is not None:
                    break

            if replay_gain is None:
                r128_tag = audio.tags.get("R128_TRACK_GAIN") or audio.tags.get("r128_track_gain")
                if r128_tag is not None:
                    try:
                        if isinstance(r128_tag, (list, tuple)):
                            r128_value = float(str(r128_tag[0]))
                        else:
                            r128_value = float(str(r128_tag))
                        # Wartości R128 przechowywane są jako dziesiętne * 256 (LUFS)
                        replay_gain = (r128_value / 256.0)
                    except (ValueError, TypeError):
                        replay_gain = None
        if hasattr(audio, "info") and getattr(audio.info, "length", None):
            duration = float(audio.info.length)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Failed to read metadata %s: %s", path, exc)

    if replay_gain is None:
        replay_gain = _scan_ape_replay_gain(path)

    cue = None
    segue = None
    segue_fade = None
    overlap = None
    intro = None
    outro = None

    def _parse_numeric_tokens(values, assume_ms=True):
        for value in values:
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                iterable = value
            else:
                iterable = [value]
            for token in iterable:
                text = str(token).strip().replace(",", ".")
                for part in text.split():
                    try:
                        num = float(part)
                        if assume_ms and abs(num) >= 100.0:
                            num /= 1000.0
                        return num
                    except ValueError:
                        continue
        return None

    if audio and audio.tags:
        try:
            txxx_list = audio.tags.getall("TXXX")  # type: ignore[attr-defined]
        except Exception:
            txxx_list = []
        if txxx_list:
            lookup = {getattr(tag, "desc", "").lower(): tag for tag in txxx_list if getattr(tag, "desc", None)}
            for key, target in (
                ("cue", "cue"),
                ("cue in", "cue"),
                ("segue", "segue"),
                ("segue fade", "segue_fade"),
                ("overlap", "overlap"),
                ("intro", "intro"),
                ("outro", "outro"),
            ):
                tag = lookup.get(key)
                if tag:
                    value = _parse_numeric_tokens(tag.text)
                    if value is not None:
                        if target == "cue":
                            cue = value
                        elif target == "segue":
                            segue = value
                        elif target == "segue_fade":
                            segue_fade = value
                        elif target == "overlap":
                            overlap = value
                        elif target == "intro":
                            intro = value
                        elif target == "outro":
                            outro = value

    def _read_sara_tag(tag: str) -> Optional[float]:
        text = _scan_ape_value(path, tag)
        if text:
            return _parse_numeric_tokens([text], assume_ms=False)
        return None

    if cue is None:
        cue = _read_sara_tag(CUE_IN_TAG)
    if segue is None:
        segue = _read_sara_tag(SEGUE_TAG)
    if segue_fade is None:
        segue_fade = _read_sara_tag(SEGUE_FADE_TAG)
    if overlap is None:
        overlap = _read_sara_tag(OVERLAP_TAG)
    if intro is None:
        intro = _read_sara_tag(INTRO_TAG)
    if outro is None:
        outro = _read_sara_tag(OUTRO_TAG)

    if cue is None:
        for candidate in ("Cue", "CueDB", "CueIn"):
            text = _scan_ape_value(path, candidate)
            if text:
                cue = _parse_numeric_tokens([text])
                if cue is not None:
                    break
    if segue is None:
        for candidate in ("Segue", "SegueDB"):
            text = _scan_ape_value(path, candidate)
            if text:
                segue = _parse_numeric_tokens([text])
                if segue is not None:
                    break
    if segue_fade is None:
        for candidate in ("SegueFade", "SegueFadeDuration"):
            text = _scan_ape_value(path, candidate)
            if text:
                segue_fade = _parse_numeric_tokens([text])
                if segue_fade is not None:
                    break
    if overlap is None:
        for candidate in ("CueOverlap", "Overlap"):
            text = _scan_ape_value(path, candidate)
            if text:
                overlap = _parse_numeric_tokens([text])
                if overlap is not None:
                    break
    if intro is None:
        for candidate in ("Intro", "IntroDB"):
            text = _scan_ape_value(path, candidate)
            if text:
                intro = _parse_numeric_tokens([text])
                if intro is not None:
                    break
    if outro is None:
        for candidate in ("Outro", "OutroDB"):
            text = _scan_ape_value(path, candidate)
            if text:
                outro = _parse_numeric_tokens([text])
                if outro is not None:
                    break

    loop_start, loop_end, loop_enabled, loop_auto_enabled = _scan_loop_values(path)
    # Jeśli flaga automatyczna jest włączona, traktuj pętlę jako aktywną przy wczytaniu.
    loop_enabled = (loop_enabled or loop_auto_enabled)

    return AudioMetadata(
        title=title,
        duration_seconds=duration,
        artist=artist,
        replay_gain_db=replay_gain,
        cue_in_seconds=cue,
        segue_seconds=segue,
        segue_fade_seconds=segue_fade,
        overlap_seconds=overlap,
        intro_seconds=intro,
        outro_seconds=outro,
        loop_start_seconds=loop_start,
        loop_end_seconds=loop_end,
        loop_auto_enabled=loop_auto_enabled,
        loop_enabled=loop_enabled,
    )

