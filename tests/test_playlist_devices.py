"""Tests for playlist device rotation and loop metadata."""

from pathlib import Path

from sara.core.playlist import PlaylistItem, PlaylistModel


def test_playlist_selects_devices_round_robin():
    playlist = PlaylistModel(id="pl-1", name="Test", output_slots=["a", "b", "c"])

    available = {"a", "b", "c"}
    busy: set[str] = set()

    sequence = [playlist.select_next_slot(available, busy) for _ in range(5)]

    assert sequence == [
        (0, "a"),
        (1, "b"),
        (2, "c"),
        (0, "a"),
        (1, "b"),
    ]


def test_playlist_skips_busy_device():
    playlist = PlaylistModel(id="pl-1", name="Test", output_slots=["a", "b"])

    available = ["a", "b"]
    busy = {"b"}

    result_first = playlist.select_next_slot(set(available), busy)
    result_second = playlist.select_next_slot(set(available), busy)

    assert result_first == (0, "a")
    assert result_second == (0, "a")


def test_playlist_fallback_to_available_devices_when_unconfigured():
    playlist = PlaylistModel(id="pl-2", name="Fallback")

    available = ["x", "y"]
    busy = set()

    result_first = playlist.select_next_slot(set(available), busy)
    result_second = playlist.select_next_slot(set(available), busy)

    assert result_first == (0, "x")
    assert result_second == (1, "y")


def test_playlist_item_loop_flags():
    playlist = PlaylistModel(id="pl-3", name="LoopTest")
    item = PlaylistItem(
        id="item-1",
        path=Path(__file__),
        title="Sample",
        duration_seconds=10.0,
    )
    playlist.items.append(item)

    assert not item.has_loop()

    item.set_loop(0.5, 2.5)
    assert item.has_loop()
    assert item.loop_start_seconds == 0.5
    assert item.loop_end_seconds == 2.5

    item.clear_loop()
    assert not item.has_loop()
    assert item.loop_start_seconds is None
    assert item.loop_end_seconds is None
