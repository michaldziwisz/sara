"""Helpers for reading and writing audio metadata."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import struct

from mutagen import File as MutagenFile
from mutagen.apev2 import APEv2, error as APEv2Error

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".flac",
    ".ogg",
    ".oga",
    ".opus",
    ".m4a",
    ".aac",
    ".aiff",
    ".aif",
    ".wma",
    ".wv",
}


def is_supported_audio_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


@dataclass(slots=True)
class AudioMetadata:
    title: str
    duration_seconds: float
    artist: Optional[str] = None
    replay_gain_db: Optional[float] = None
    cue_in_seconds: Optional[float] = None
    segue_seconds: Optional[float] = None
    overlap_seconds: Optional[float] = None
    intro_seconds: Optional[float] = None
    loop_start_seconds: Optional[float] = None
    loop_end_seconds: Optional[float] = None
    loop_enabled: bool = False


LOOP_START_TAG = "SARA_LOOP_START"
LOOP_END_TAG = "SARA_LOOP_END"
LOOP_ENABLED_TAG = "SARA_LOOP_ENABLED"


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


def _read_ape_tags(path: Path) -> dict[str, str]:
    try:
        data = path.read_bytes()
    except OSError:
        return {}
    marker = b"APETAGEX"
    idx = data.rfind(marker)
    if idx == -1 or idx + 32 > len(data):
        return {}
    magic, version, size, count, flags, reserved = struct.unpack('<8sIIIIQ', data[idx:idx+32])
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
        value_size, item_flags = struct.unpack_from('<II', items, pos)
        pos += 8
        end_key = items.find(b'\x00', pos)
        if end_key == -1:
            break
        key = items[pos:end_key].decode('utf-8', errors='ignore')
        pos = end_key + 1
        value_bytes = items[pos:pos + value_size]
        pos += value_size
        value = value_bytes.rstrip(b'\x00').decode('utf-8', errors='ignore')
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
        text = text.replace(',', '.')
        if text.lower().endswith("db"):
            text = text[:-2].strip()
        for token in text.split():
            try:
                return float(token)
            except ValueError:
                continue
    return None


def _scan_loop_values(path: Path) -> tuple[Optional[float], Optional[float], bool]:
    tags = _read_ape_tags(path)
    if not tags:
        return None, None, False

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

    if start is None or end is None or end <= start:
        return None, None, False

    return start, end, enabled


def save_loop_metadata(
    path: Path,
    start: Optional[float],
    end: Optional[float],
    enabled: Optional[bool] = None,
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
                if key in (LOOP_START_TAG, LOOP_END_TAG, LOOP_ENABLED_TAG):
                    continue
                tags[key] = value

    if tags is None:
        logger.warning("Unable to initialise APE tags for %s", path)
        return False

    try:
        if start is None or end is None:
            removed = False
            for key in (LOOP_START_TAG, LOOP_END_TAG, LOOP_ENABLED_TAG):
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
        tags.save(file_path)
        return True
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Failed to update loop tags for %s: %s", path, exc)
        return False


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
    overlap = None
    intro = None

    def _parse_numeric_tokens(values, assume_ms=True):
        for value in values:
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                iterable = value
            else:
                iterable = [value]
            for token in iterable:
                text = str(token).strip().replace(',', '.')
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
            for key, target in (("cue", "cue"), ("cue in", "cue"), ("segue", "segue"), ("overlap", "overlap"), ("intro", "intro")):
                tag = lookup.get(key)
                if tag:
                    value = _parse_numeric_tokens(tag.text)
                    if value is not None:
                        if key.startswith("cue"):
                            cue = value
                        elif key == "segue":
                            segue = value
                        elif key == "overlap":
                            overlap = value
                        elif key == "intro":
                            intro = value

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

    loop_start, loop_end, loop_enabled = _scan_loop_values(path)
    if loop_start is None or loop_end is None:
        loop_enabled = False

    return AudioMetadata(
        title=title,
        duration_seconds=duration,
        artist=artist,
        replay_gain_db=replay_gain,
        cue_in_seconds=cue,
        segue_seconds=segue,
        overlap_seconds=overlap,
        intro_seconds=intro,
        loop_start_seconds=loop_start,
        loop_end_seconds=loop_end,
        loop_enabled=loop_enabled,
    )
