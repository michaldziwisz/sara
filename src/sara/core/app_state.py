"""Central application state and playlist management."""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from sara.core.playlist import PlaylistItem, PlaylistKind, PlaylistModel


@dataclass
class AppState:
    """Store a collection of playlists and user preferences."""

    playlists: Dict[str, PlaylistModel] = field(default_factory=dict)

    def add_playlist(self, model: PlaylistModel) -> None:
        self.playlists[model.id] = model

    def remove_playlist(self, playlist_id: str) -> None:
        self.playlists.pop(playlist_id, None)

    def iter_playlists(self) -> Iterable[PlaylistModel]:
        return self.playlists.values()


class PlaylistFactory:
    """Tworzy nowe playlisty i pozycje z unikatowymi identyfikatorami."""

    def __init__(self) -> None:
        self._playlist_counter = itertools.count(1)

    def create_playlist(
        self,
        name: str,
        *,
        kind: PlaylistKind = PlaylistKind.MUSIC,
        items: List[PlaylistItem] | None = None,
    ) -> PlaylistModel:
        playlist_id = f"pl-{next(self._playlist_counter)}-{uuid.uuid4().hex[:6]}"
        return PlaylistModel(id=playlist_id, name=name, items=items or [], kind=kind)

    @staticmethod
    def create_item(
        path: Path,
        title: str,
        duration_seconds: float,
        artist: str | None = None,
        replay_gain_db: float | None = None,
        cue_in_seconds: float | None = None,
        segue_seconds: float | None = None,
        segue_fade_seconds: float | None = None,
        overlap_seconds: float | None = None,
        intro_seconds: float | None = None,
        outro_seconds: float | None = None,
        loop_start_seconds: float | None = None,
        loop_end_seconds: float | None = None,
        loop_auto_enabled: bool = False,
        loop_enabled: bool = False,
    ) -> PlaylistItem:
        item_id = uuid.uuid4().hex
        return PlaylistItem(
            id=item_id,
            path=path,
            title=title,
            duration_seconds=duration_seconds,
            artist=artist,
            replay_gain_db=replay_gain_db,
            cue_in_seconds=cue_in_seconds,
            segue_seconds=segue_seconds,
            segue_fade_seconds=segue_fade_seconds,
            overlap_seconds=overlap_seconds,
            intro_seconds=intro_seconds,
            outro_seconds=outro_seconds,
            loop_start_seconds=loop_start_seconds,
            loop_end_seconds=loop_end_seconds,
            loop_auto_enabled=loop_auto_enabled,
            loop_enabled=loop_enabled,
        )
