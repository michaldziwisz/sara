from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

if "wx" not in sys.modules:
    sys.modules["wx"] = types.SimpleNamespace(
        GetApp=lambda: None,
        CallAfter=lambda func, *args, **kwargs: func(*args, **kwargs),
    )

from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistKind, PlaylistModel
from sara.ui.controllers.playback.finish import handle_playback_finished
from sara.ui.controllers.playback.start import start_playback
from sara.ui.controllers.playback.state import stop_playlist_playback


def test_start_playback_updates_single_row_without_full_refresh(tmp_path: Path) -> None:
    track_path = tmp_path / "track.wav"
    track_path.write_text("dummy")
    item = PlaylistItem(id="item-1", path=track_path, title="Track", duration_seconds=10.0)
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    playlist.add_items([item])

    updated: list[str] = []

    def _refresh(*_args, **_kwargs) -> None:
        raise AssertionError("Full refresh should be avoided during playback start")

    panel = SimpleNamespace(
        model=playlist,
        update_item_display=lambda item_id: updated.append(item_id),
        refresh=_refresh,
        mark_item_status=lambda *_a, **_k: None,
        select_index=lambda *_a, **_k: None,
    )

    frame = SimpleNamespace(
        _stop_preview=lambda: None,
        _auto_mix_enabled=True,
        _fade_duration=0.0,
        _focus_playing_track=True,
        _active_break_item={},
        _playback=SimpleNamespace(
            contexts={},
            auto_mix_state={},
            start_item=lambda *_a, **_k: SimpleNamespace(player=object(), device_id="dev-1", slot_index=0),
        ),
        _get_playback_context=lambda _playlist_id: None,
        _stop_playlist_playback=lambda *_a, **_k: None,
        _supports_mix_trigger=lambda _p: False,
        _resolve_mix_timing=lambda itm, effective_duration_override=None: (
            None,
            0.0,
            itm.cue_in_seconds or 0.0,
            itm.effective_duration_seconds,
        ),
        _register_mix_plan=lambda *_a, **_k: None,
        _adjust_duration_and_mix_trigger=lambda *_a, **_k: None,
        _focus_lock={},
        _last_started_item_id={},
        _sync_loop_mix_trigger=lambda *_a, **_k: None,
        _maybe_focus_playing_item=lambda *_a, **_k: None,
        _announce_event=lambda *_a, **_k: None,
    )

    assert (
        start_playback(
            frame,
            panel,
            item,
            restart_playing=False,
            auto_mix_sequence=True,
            prefer_overlap=False,
        )
        is True
    )
    assert updated == ["item-1"]


def test_playback_finished_updates_single_row_without_full_refresh(tmp_path: Path) -> None:
    track_path = tmp_path / "track.wav"
    track_path.write_text("dummy")
    item = PlaylistItem(
        id="item-1",
        path=track_path,
        title="Track",
        duration_seconds=10.0,
        status=PlaylistItemStatus.PLAYING,
    )
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    playlist.add_items([item])

    updated: list[str] = []

    def _refresh(*_args, **_kwargs) -> None:
        raise AssertionError("Full refresh should be avoided during playback finish")

    panel = SimpleNamespace(
        model=playlist,
        update_item_display=lambda item_id: updated.append(item_id),
        refresh=_refresh,
        mark_item_status=lambda *_a, **_k: None,
    )

    class _Player:
        def set_finished_callback(self, _cb):
            return None

        def set_progress_callback(self, _cb):
            return None

        def stop(self):
            return None

    context = SimpleNamespace(player=_Player())

    frame = SimpleNamespace(
        _playback=SimpleNamespace(
            contexts={(playlist.id, item.id): context},
            auto_mix_state={},
        ),
        _mix_plans={},
        _mix_trigger_points={},
        _clear_mix_plan=lambda *_a, **_k: None,
        _playlists={playlist.id: panel},
        _auto_remove_played=False,
        _remove_item_from_playlist=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not remove")),
        _announce_event=lambda *_a, **_k: None,
        _auto_mix_enabled=False,
        _get_playback_context=lambda *_a, **_k: None,
        _playlist_has_selection=lambda *_a, **_k: False,
        _active_break_item={},
        _auto_mix_tracker=SimpleNamespace(set_last_started=lambda *_a, **_k: None),
    )

    handle_playback_finished(frame, playlist.id, item.id)

    assert item.status is PlaylistItemStatus.PLAYED
    assert updated == ["item-1"]


def test_stop_playlist_updates_single_row_without_full_refresh(tmp_path: Path) -> None:
    track_path = tmp_path / "track.wav"
    track_path.write_text("dummy")
    item = PlaylistItem(
        id="item-1",
        path=track_path,
        title="Track",
        duration_seconds=10.0,
        status=PlaylistItemStatus.PLAYING,
    )
    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    playlist.add_items([item])

    updated: list[str] = []

    def _refresh(*_args, **_kwargs) -> None:
        raise AssertionError("Full refresh should be avoided during stop_playlist")

    panel = SimpleNamespace(
        model=playlist,
        update_item_display=lambda item_id: updated.append(item_id),
        refresh=_refresh,
        mark_item_status=lambda *_a, **_k: None,
        update_progress=lambda *_a, **_k: None,
    )

    frame = SimpleNamespace(
        _played_tracks_logger=None,
        _now_playing_writer=None,
        _clear_mix_plan=lambda *_a, **_k: None,
        _playback=SimpleNamespace(
            stop_playlist=lambda playlist_id, fade_duration=0.0: [((playlist_id, item.id), SimpleNamespace())],
        ),
        _playlists={playlist.id: panel},
    )

    stop_playlist_playback(frame, playlist.id, mark_played=True, fade_duration=0.0)

    assert item.status is PlaylistItemStatus.PLAYED
    assert updated == ["item-1"]
