"""Services for logging played tracks to disk (streaming support)."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from sara.core.config import SettingsManager
from sara.core.playlist import PlaylistItem, PlaylistItemType, PlaylistModel


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlayedTrackEntry:
    played_at: datetime
    artist: str
    title: str
    played_seconds: float


def resolve_played_tracks_log_root(settings: SettingsManager, *, output_dir: Path) -> Path:
    configured = settings.get_played_tracks_logging_folder()
    if configured is None:
        return output_dir / "logs"
    if configured.is_absolute():
        return configured
    return output_dir / configured


def resolve_played_tracks_log_path(log_root: Path, played_at: datetime) -> Path:
    return (
        log_root
        / played_at.strftime("%Y")
        / played_at.strftime("%m")
        / played_at.strftime("%d")
        / f"{played_at.strftime('%H')}.csv"
    )


class PlayedTracksLogger:
    """Append track play entries to hourly CSV files."""

    def __init__(
        self,
        settings: SettingsManager,
        *,
        output_dir: Path,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._settings = settings
        self._output_dir = Path(output_dir)
        self._now = now
        self._started_at: dict[tuple[str, str], datetime] = {}
        self._last_progress_seconds: dict[tuple[str, str], float] = {}

    def on_started(
        self,
        playlist: PlaylistModel,
        item: PlaylistItem,
        *,
        started_at: datetime | None = None,
    ) -> None:
        if started_at is None:
            started_at = self._now()
        key = (playlist.id, item.id)
        self._started_at[key] = started_at
        self._last_progress_seconds.pop(key, None)

    def on_progress(self, playlist_id: str, item_id: str, seconds: float) -> None:
        key = (playlist_id, item_id)
        if key not in self._started_at:
            return
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return
        if value < 0:
            return
        self._last_progress_seconds[key] = value

    def on_finished(
        self,
        playlist: PlaylistModel,
        item: PlaylistItem,
        *,
        finished_at: datetime | None = None,
    ) -> None:
        self._finalize(playlist, item, ended_at=finished_at)

    def on_stopped(
        self,
        playlist: PlaylistModel,
        item: PlaylistItem,
        *,
        mark_played: bool,
        stopped_at: datetime | None = None,
    ) -> None:
        if not mark_played:
            self._forget(playlist.id, item.id)
            return
        self._finalize(playlist, item, ended_at=stopped_at)

    def _forget(self, playlist_id: str, item_id: str) -> None:
        key = (playlist_id, item_id)
        self._started_at.pop(key, None)
        self._last_progress_seconds.pop(key, None)

    def _finalize(self, playlist: PlaylistModel, item: PlaylistItem, *, ended_at: datetime | None) -> None:
        if not self._settings.get_played_tracks_logging_enabled():
            self._forget(playlist.id, item.id)
            return
        if not self._should_log_type(item):
            self._forget(playlist.id, item.id)
            return

        key = (playlist.id, item.id)
        started_at = self._started_at.get(key)
        if started_at is None:
            return
        ended_at = ended_at or self._now()

        played_seconds = self._resolve_played_seconds(item, key=key, started_at=started_at, ended_at=ended_at)
        entry = PlayedTrackEntry(
            played_at=started_at,
            artist=(item.artist or "").strip(),
            title=str(item.title or "").strip(),
            played_seconds=played_seconds,
        )
        self._append_entry(entry)
        self._forget(playlist.id, item.id)

    def _should_log_type(self, item: PlaylistItem) -> bool:
        item_type = getattr(item, "item_type", PlaylistItemType.SONG)
        if item_type is PlaylistItemType.SONG:
            return bool(self._settings.get_played_tracks_logging_songs_enabled())
        if item_type is PlaylistItemType.SPOT:
            return bool(self._settings.get_played_tracks_logging_spots_enabled())
        return True

    def _resolve_played_seconds(
        self,
        item: PlaylistItem,
        *,
        key: tuple[str, str],
        started_at: datetime,
        ended_at: datetime,
    ) -> float:
        cue = float(getattr(item, "cue_in_seconds", 0.0) or 0.0)
        progress = self._last_progress_seconds.get(key)
        played_seconds: float
        if progress is not None:
            played_seconds = max(0.0, float(progress) - cue)
        else:
            played_seconds = max(0.0, (ended_at - started_at).total_seconds())
        try:
            effective = float(getattr(item, "effective_duration_seconds", played_seconds))
        except Exception:
            effective = played_seconds
        if effective > 0:
            played_seconds = min(played_seconds, effective)
        return played_seconds

    def _append_entry(self, entry: PlayedTrackEntry) -> None:
        log_root = resolve_played_tracks_log_root(self._settings, output_dir=self._output_dir)
        path = resolve_played_tracks_log_path(log_root, entry.played_at)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            needs_header = (not path.exists()) or path.stat().st_size == 0
            with path.open("a", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                if needs_header:
                    writer.writerow(["artist", "title", "played_at", "played_seconds"])
                writer.writerow(
                    [
                        entry.artist,
                        entry.title,
                        entry.played_at.strftime("%Y-%m-%d %H:%M:%S"),
                        f"{entry.played_seconds:.3f}",
                    ]
                )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to append played-tracks entry: %s", exc)


__all__ = [
    "PlayedTrackEntry",
    "PlayedTracksLogger",
    "resolve_played_tracks_log_path",
    "resolve_played_tracks_log_root",
]
