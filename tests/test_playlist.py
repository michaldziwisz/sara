from pathlib import Path

from sara.core.playlist import (
    PlaylistItem,
    PlaylistItemStatus,
    PlaylistModel,
)


def _make_item(item_id: str, *, status: PlaylistItemStatus = PlaylistItemStatus.PENDING) -> PlaylistItem:
    return PlaylistItem(
        id=item_id,
        path=Path(f"/tmp/{item_id}.mp3"),
        title=f"Track {item_id}",
        duration_seconds=120.0,
        status=status,
        current_position=50.0 if status is PlaylistItemStatus.PLAYED else 0.0,
    )


def test_toggle_selection_resets_state_to_pending() -> None:
    item = _make_item("one", status=PlaylistItemStatus.PLAYED)
    playlist = PlaylistModel(id="pl", name="Test", items=[item])

    was_selected = playlist.toggle_selection(item.id)

    assert was_selected is True
    assert item.is_selected is True
    assert item.status is PlaylistItemStatus.PENDING
    assert item.current_position == 0.0


def test_next_selected_item_id_prefers_pending_or_paused() -> None:
    pending = _make_item("pending", status=PlaylistItemStatus.PENDING)
    playing = _make_item("playing", status=PlaylistItemStatus.PLAYING)
    paused = _make_item("paused", status=PlaylistItemStatus.PAUSED)
    playlist = PlaylistModel(id="pl", name="Test", items=[pending, playing, paused])

    playlist.toggle_selection("playing")
    playing.status = PlaylistItemStatus.PLAYING
    playlist.toggle_selection("pending")
    playlist.toggle_selection("paused")

    # playing selection should be ignored because status is not pending/paused
    assert playlist.next_selected_item_id() == "pending"

    playlist.clear_selection("pending")
    assert playlist.next_selected_item_id() == "paused"


def test_clear_selection_resets_flags() -> None:
    items = [_make_item(str(idx)) for idx in range(3)]
    playlist = PlaylistModel(id="pl", name="Test", items=items)

    for item in items:
        playlist.toggle_selection(item.id)

    playlist.clear_selection()

    assert all(not item.is_selected for item in items)


def test_begin_next_item_replays_played_preferred_track() -> None:
    played = _make_item("a", status=PlaylistItemStatus.PLAYED)
    playlist = PlaylistModel(id="pl", name="Test", items=[played])

    result = playlist.begin_next_item(played.id)

    assert result is played
    assert played.status is PlaylistItemStatus.PLAYING
    assert played.current_position == 0.0
