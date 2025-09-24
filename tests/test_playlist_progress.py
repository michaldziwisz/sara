from pathlib import Path
from sara.core.playlist import PlaylistItem, PlaylistItemStatus


def test_playlist_item_progress_display_updates_status():
    item = PlaylistItem(
        id="1",
        path=Path(__file__),
        title="Test",
        duration_seconds=300,
    )

    assert item.status is PlaylistItemStatus.PENDING
    assert item.progress_display.startswith("00:00")

    item.update_progress(42)
    assert item.status is PlaylistItemStatus.PLAYING
    assert "00:42" in item.progress_display

    item.update_progress(600)
    assert item.current_position == item.duration_seconds
    assert item.progress_display.endswith("05:00")
