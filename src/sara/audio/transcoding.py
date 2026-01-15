"""Helpers for transcoding audio files for playback."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple


TRANSCODE_EXTENSIONS = {
    ".m4a",
    ".m4v",
    ".mp2",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
}


def transcode_source_to_wav(source: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg jest wymagany do odtwarzania plików wymagających transkodowania (MP4/M4A/MPEG)")
    fd, temp_name = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    target = Path(temp_name)
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(target),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError as exc:  # pragma: no cover - zależy od środowiska
        target.unlink(missing_ok=True)
        raise RuntimeError("FFmpeg nie został znaleziony w PATH") from exc
    except subprocess.CalledProcessError as exc:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"FFmpeg nie mógł zdekodować pliku {source.name}") from exc
    return target


def open_audio_file_with_transcoding(
    path: Path,
    *,
    sf,
    transcode_extensions: Optional[set[str]] = None,
) -> Tuple[object, Optional[Path]]:
    if transcode_extensions is None:
        transcode_extensions = TRANSCODE_EXTENSIONS

    try:
        return sf.SoundFile(path, mode="r"), None
    except Exception:
        if path.suffix.lower() not in transcode_extensions:
            raise
        wav_path = transcode_source_to_wav(path)
        try:
            sound_file = sf.SoundFile(wav_path, mode="r")
        except Exception as exc:  # pylint: disable=broad-except
            try:
                wav_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise RuntimeError("Nie udało się odczytać przekodowanego pliku MP4") from exc
        return sound_file, wav_path
