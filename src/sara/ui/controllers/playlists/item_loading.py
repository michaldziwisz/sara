"""Item loading/metadata extraction helpers."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Thread
from typing import Any, Callable

import wx

from sara.core.media_metadata import AudioMetadata, extract_metadata, is_supported_audio_file


logger = logging.getLogger(__name__)


def collect_files_from_paths(paths: list[Path]) -> tuple[list[Path], int]:
    files: list[Path] = []
    skipped = 0
    for path in paths:
        if path.is_file():
            if is_supported_audio_file(path):
                files.append(path)
            else:
                skipped += 1
            continue
        if path.is_dir():
            try:
                for file_path in sorted(path.rglob("*")):
                    if file_path.is_file():
                        if is_supported_audio_file(file_path):
                            files.append(file_path)
                        else:
                            skipped += 1
            except Exception as exc:
                logger.warning("Failed to enumerate %s: %s", path, exc)
    return files, skipped


def metadata_worker_count(total: int) -> int:
    if total <= 1:
        return 1
    cpu = os.cpu_count() or 4
    return max(1, min(cpu, 8, total))


def build_playlist_item(
    frame,
    path: Path,
    metadata: AudioMetadata,
    *,
    override_title: str | None = None,
    override_artist: str | None = None,
    override_duration: float | None = None,
):
    title = override_title or metadata.title or path.stem
    artist = override_artist or metadata.artist
    duration = override_duration if override_duration is not None else metadata.duration_seconds
    return frame._playlist_factory.create_item(
        path=path,
        title=title,
        artist=artist,
        duration_seconds=duration,
        replay_gain_db=metadata.replay_gain_db,
        cue_in_seconds=metadata.cue_in_seconds,
        segue_seconds=metadata.segue_seconds,
        segue_fade_seconds=metadata.segue_fade_seconds,
        overlap_seconds=metadata.overlap_seconds,
        intro_seconds=metadata.intro_seconds,
        outro_seconds=metadata.outro_seconds,
        loop_start_seconds=metadata.loop_start_seconds,
        loop_end_seconds=metadata.loop_end_seconds,
        loop_auto_enabled=metadata.loop_auto_enabled,
        loop_enabled=metadata.loop_enabled,
    )


def load_playlist_item(frame, path: Path, entry: dict[str, Any] | None = None):
    if not path.exists():
        logger.warning("Playlist entry %s does not exist", path)
        return None
    try:
        metadata: AudioMetadata = extract_metadata(path)
    except Exception as exc:  # pylint: disable=broad-except
        if entry is None:
            logger.warning("Failed to read metadata from %s: %s", path, exc)
            return None
        logger.warning("Using fallback metadata for %s: %s", path, exc)
        metadata = AudioMetadata(
            title=entry.get("title") or path.stem,
            duration_seconds=float(entry.get("duration") or 0.0),
            artist=entry.get("artist"),
        )
    override_title = entry.get("title") if entry else None
    override_artist = entry.get("artist") if entry else None
    override_duration = None
    if entry:
        duration = entry.get("duration")
        if duration is not None:
            override_duration = float(duration or 0.0)
    return build_playlist_item(
        frame,
        path,
        metadata,
        override_title=override_title,
        override_artist=override_artist,
        override_duration=override_duration,
    )


def load_items_from_sources(frame, sources: list[tuple[Path, dict[str, Any] | None]]):
    if not sources:
        return []
    worker_count = frame._metadata_worker_count(len(sources))
    if worker_count <= 1:
        items = [frame._load_playlist_item(path, entry) for path, entry in sources]
    else:
        paths, entries = zip(*sources)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            items = list(executor.map(frame._load_playlist_item, paths, entries))
    return [item for item in items if item is not None]


def create_items_from_paths(frame, file_paths: list[Path]):
    sources = [(path, None) for path in file_paths]
    return frame._load_items_from_sources(sources)


def create_items_from_m3u_entries(frame, entries: list[dict[str, Any]]):
    sources: list[tuple[Path, dict[str, Any] | None]] = []
    for entry in entries:
        audio_path = Path(entry["path"])
        sources.append((audio_path, entry))
    return frame._load_items_from_sources(sources)


def run_item_loader(
    frame,
    *,
    description: str,
    worker: Callable[[], Any],
    on_complete: Callable[[Any], None],
) -> None:
    busy = wx.BusyInfo(description, parent=frame)
    holder: dict[str, wx.BusyInfo | None] = {"busy": busy}

    def task() -> None:
        try:
            result = worker()
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to load playlist items: %s", exc)
            result = []

        def finish() -> None:
            busy_obj = holder.pop("busy", None)
            if busy_obj is not None:
                del busy_obj
            on_complete(result)

        wx.CallAfter(finish)

    Thread(target=task, daemon=True).start()
