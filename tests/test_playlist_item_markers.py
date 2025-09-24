from pathlib import Path

from sara.core.playlist import PlaylistItem, PlaylistItemStatus


def test_playlist_item_cue_adjusts_progress_and_duration():
    item = PlaylistItem(
        id="i1",
        path=Path("dummy.mp3"),
        title="Test",
        duration_seconds=200.0,
        cue_in_seconds=5.0,
    )

    assert item.effective_duration_seconds == 195.0
    item.update_progress(7.5)
    assert item.current_position == 2.5
    assert item.status is PlaylistItemStatus.PLAYING

    item.update_progress(250.0)
    assert item.current_position == item.effective_duration_seconds


def test_playlist_item_loop_flags_still_available():
    item = PlaylistItem(
        id="i2",
        path=Path("dummy2.mp3"),
        title="Loop",
        duration_seconds=120.0,
    )
    assert not item.has_loop()
    item.set_loop(5.0, 10.0)
    assert item.has_loop()
    item.clear_loop()
    assert not item.has_loop()
