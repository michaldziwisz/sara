from pathlib import Path

from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistModel


def _make_item(identifier: str) -> PlaylistItem:
    return PlaylistItem(
        id=identifier,
        path=Path(f"/tmp/{identifier}.wav"),
        title=f"Utwór {identifier}",
        duration_seconds=120.0,
    )


def test_toggle_selection_marks_single_item():
    playlist = PlaylistModel(id="pl-1", name="Test", items=[_make_item(str(i)) for i in range(3)])

    playlist.toggle_selection("1")

    assert [item.is_selected for item in playlist.items] == [False, True, False]

    playlist.toggle_selection("1")

    assert all(not item.is_selected for item in playlist.items)


def test_begin_next_item_prefers_selected_item():
    playlist = PlaylistModel(id="pl-2", name="Test", items=[_make_item(str(i)) for i in range(3)])
    selected_id = playlist.items[1].id
    playlist.toggle_selection(selected_id)

    item = playlist.begin_next_item(selected_id)

    assert item is playlist.items[1]
    assert playlist.items[1].status is PlaylistItemStatus.PLAYING
    assert playlist.items[0].status is PlaylistItemStatus.PENDING

    playlist.items[1].status = PlaylistItemStatus.PLAYED
    next_item = playlist.begin_next_item(selected_id)

    assert next_item is playlist.items[0]


def test_begin_next_item_resumes_paused_selection():
    playlist = PlaylistModel(id="pl-3", name="Test", items=[_make_item(str(i)) for i in range(2)])
    selected_id = playlist.items[0].id
    playlist.toggle_selection(selected_id)
    playlist.items[0].status = PlaylistItemStatus.PAUSED

    resumed = playlist.begin_next_item(selected_id)

    assert resumed is playlist.items[0]
    assert playlist.items[0].status is PlaylistItemStatus.PLAYING
