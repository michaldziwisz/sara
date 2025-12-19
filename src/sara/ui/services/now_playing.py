"""Services for writing a now-playing text file (streaming support)."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from sara.core.config import SettingsManager
from sara.core.playlist import PlaylistItem, PlaylistItemType, PlaylistModel


logger = logging.getLogger(__name__)

_TOKEN_PATTERN = re.compile(r"%([a-zA-Z_]+)")


def resolve_now_playing_path(settings: SettingsManager, *, output_dir: Path) -> Path:
    configured = settings.get_now_playing_path()
    if configured is None:
        return output_dir / "nowplaying.txt"
    if configured.is_absolute():
        return configured
    return output_dir / configured


def write_now_playing_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@dataclass
class NowPlayingState:
    playlist_id: str
    playlist_name: str
    item_id: str
    artist: str
    title: str
    item_type: PlaylistItemType
    cue_in_seconds: float
    started_at: datetime
    progress_seconds: float | None = None


def render_now_playing(template: str, state: NowPlayingState) -> str:
    raw = (template or "").strip()
    if not raw:
        raw = "%artist - %title"

    def repl(match: re.Match[str]) -> str:
        token = match.group(1).lower()
        if token == "artist":
            return state.artist
        if token == "title":
            return state.title
        if token == "playlist":
            return state.playlist_name
        if token == "type":
            return state.item_type.value
        if token == "elapsed":
            seconds = state.progress_seconds
            if seconds is None:
                return ""
            effective = max(0.0, float(seconds) - state.cue_in_seconds)
            return f"{effective:.1f}"
        return match.group(0)

    return _TOKEN_PATTERN.sub(repl, raw).strip()


class NowPlayingWriter:
    """Write current track information to a single text file."""

    def __init__(
        self,
        settings: SettingsManager,
        *,
        output_dir: Path,
        now: Callable[[], datetime] = datetime.now,
        monotonic: Callable[[], float] = time.monotonic,
        writer: Callable[[Path, str], None] = write_now_playing_text,
    ) -> None:
        self._settings = settings
        self._output_dir = Path(output_dir)
        self._now = now
        self._monotonic = monotonic
        self._writer = writer
        self._state: NowPlayingState | None = None
        self._current_key: tuple[str, str] | None = None
        self._last_write: float | None = None

    def on_started(
        self,
        playlist: PlaylistModel,
        item: PlaylistItem,
        *,
        started_at: datetime | None = None,
    ) -> None:
        started_at = started_at or self._now()
        cue_in = float(getattr(item, "cue_in_seconds", 0.0) or 0.0)
        item_type = getattr(item, "item_type", PlaylistItemType.SONG)
        state = NowPlayingState(
            playlist_id=playlist.id,
            playlist_name=playlist.name,
            item_id=item.id,
            artist=(item.artist or "").strip(),
            title=str(item.title or "").strip(),
            item_type=item_type if isinstance(item_type, PlaylistItemType) else PlaylistItemType.SONG,
            cue_in_seconds=cue_in,
            started_at=started_at,
            progress_seconds=None,
        )
        self._state = state
        self._current_key = (playlist.id, item.id)
        self._last_write = None

        if not self._settings.get_now_playing_enabled():
            return
        if self._settings.get_now_playing_update_on_track_change():
            self._write_current()

    def refresh(self) -> None:
        if not self._settings.get_now_playing_enabled():
            return
        if self._state is None:
            self._write_text("")
        else:
            self._write_current()

    def on_progress(self, playlist_id: str, item_id: str, seconds: float) -> None:
        if not self._settings.get_now_playing_enabled():
            return
        if self._current_key != (playlist_id, item_id) or self._state is None:
            return
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return
        if value < 0:
            return
        self._state.progress_seconds = value
        interval = float(self._settings.get_now_playing_update_interval_seconds() or 0.0)
        if interval <= 0:
            return
        now_mono = self._monotonic()
        if self._last_write is None or (now_mono - self._last_write) >= interval:
            self._write_current()

    def on_finished(self, playlist_id: str, item_id: str) -> None:
        self._maybe_clear(playlist_id, item_id)

    def on_stopped(self, playlist_id: str, item_id: str) -> None:
        self._maybe_clear(playlist_id, item_id)

    def _maybe_clear(self, playlist_id: str, item_id: str) -> None:
        if self._current_key != (playlist_id, item_id):
            return
        self._current_key = None
        self._state = None
        self._last_write = None
        if not self._settings.get_now_playing_enabled():
            return
        self._write_text("")

    def _write_current(self) -> None:
        if not self._state:
            return
        if not self._should_include_type(self._state.item_type):
            self._write_text("")
            return
        template = self._settings.get_now_playing_template()
        text = render_now_playing(template, self._state)
        self._write_text(text)

    def _should_include_type(self, item_type: PlaylistItemType) -> bool:
        if item_type is PlaylistItemType.SONG:
            return bool(self._settings.get_now_playing_songs_enabled())
        if item_type is PlaylistItemType.SPOT:
            return bool(self._settings.get_now_playing_spots_enabled())
        return True

    def _write_text(self, text: str) -> None:
        path = resolve_now_playing_path(self._settings, output_dir=self._output_dir)
        try:
            payload = text.rstrip("\n") + "\n" if text else ""
            self._writer(path, payload)
            self._last_write = self._monotonic()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to update now-playing file %s: %s", path, exc)


__all__ = [
    "NowPlayingState",
    "NowPlayingWriter",
    "render_now_playing",
    "resolve_now_playing_path",
    "write_now_playing_text",
]
