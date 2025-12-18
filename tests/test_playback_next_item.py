from __future__ import annotations

from pathlib import Path

from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistKind, PlaylistModel
from sara.ui.controllers.playback_next_item import decide_next_item


def _make_playlist(tmp_path: Path, statuses: list[PlaylistItemStatus], *, kind: PlaylistKind = PlaylistKind.MUSIC) -> PlaylistModel:
    playlist = PlaylistModel(id="pl-1", name="P", kind=kind)
    items: list[PlaylistItem] = []
    for idx, status in enumerate(statuses):
        item_id = chr(ord("a") + idx)
        items.append(
            PlaylistItem(
                id=item_id,
                path=tmp_path / f"{item_id}.wav",
                title=item_id.upper(),
                duration_seconds=1.0,
                status=status,
            )
        )
    playlist.add_items(items)
    return playlist


def test_decide_next_item_prefers_model_selection(tmp_path: Path) -> None:
    playlist = _make_playlist(
        tmp_path,
        [PlaylistItemStatus.PENDING, PlaylistItemStatus.PENDING, PlaylistItemStatus.PENDING],
    )
    playlist.items[1].is_selected = True

    decision = decide_next_item(
        playlist,
        panel_selected_indices=[],
        panel_focus_index=-1,
        ignore_ui_selection=False,
        last_started_item_id=None,
        break_target_index=None,
        restart_playing=False,
        current_playing_item_id=None,
    )

    assert decision.preferred_item_id == "b"
    assert decision.play_index == 1
    assert decision.consumed_model_selection is True
    assert decision.used_ui_selection is False


def test_decide_next_item_break_resume_skips_paused(tmp_path: Path) -> None:
    playlist = _make_playlist(tmp_path, [PlaylistItemStatus.PAUSED, PlaylistItemStatus.PENDING])

    decision = decide_next_item(
        playlist,
        panel_selected_indices=[],
        panel_focus_index=-1,
        ignore_ui_selection=False,
        last_started_item_id=None,
        break_target_index=0,
        restart_playing=False,
        current_playing_item_id=None,
    )

    assert decision.preferred_item_id == "b"
    assert decision.play_index == 1


def test_decide_next_item_after_last_played_prefers_pending(tmp_path: Path) -> None:
    playlist = _make_playlist(
        tmp_path,
        [PlaylistItemStatus.PLAYED, PlaylistItemStatus.PAUSED, PlaylistItemStatus.PENDING],
    )

    decision = decide_next_item(
        playlist,
        panel_selected_indices=[],
        panel_focus_index=-1,
        ignore_ui_selection=False,
        last_started_item_id="a",
        break_target_index=None,
        restart_playing=False,
        current_playing_item_id=None,
    )

    assert decision.preferred_item_id == "c"
    assert decision.play_index == 2


def test_decide_next_item_uses_ui_selection_order(tmp_path: Path) -> None:
    playlist = _make_playlist(tmp_path, [PlaylistItemStatus.PENDING, PlaylistItemStatus.PENDING, PlaylistItemStatus.PENDING])

    decision = decide_next_item(
        playlist,
        panel_selected_indices=[2, 1],
        panel_focus_index=-1,
        ignore_ui_selection=False,
        last_started_item_id=None,
        break_target_index=None,
        restart_playing=False,
        current_playing_item_id=None,
    )

    assert decision.preferred_item_id == "c"
    assert decision.play_index == 2
    assert decision.used_ui_selection is True


def test_decide_next_item_uses_focus_when_no_selection(tmp_path: Path) -> None:
    playlist = _make_playlist(tmp_path, [PlaylistItemStatus.PENDING, PlaylistItemStatus.PENDING])

    decision = decide_next_item(
        playlist,
        panel_selected_indices=[],
        panel_focus_index=1,
        ignore_ui_selection=False,
        last_started_item_id=None,
        break_target_index=None,
        restart_playing=False,
        current_playing_item_id=None,
    )

    assert decision.preferred_item_id == "b"
    assert decision.play_index == 1
    assert decision.used_ui_selection is True


def test_decide_next_item_ignore_ui_selection_uses_derived_next(tmp_path: Path) -> None:
    playlist = _make_playlist(tmp_path, [PlaylistItemStatus.PENDING, PlaylistItemStatus.PENDING])

    decision = decide_next_item(
        playlist,
        panel_selected_indices=[1],
        panel_focus_index=1,
        ignore_ui_selection=True,
        last_started_item_id=None,
        break_target_index=None,
        restart_playing=False,
        current_playing_item_id=None,
    )

    assert decision.preferred_item_id == "a"
    assert decision.play_index == 0
    assert decision.used_ui_selection is False


def test_decide_next_item_restart_playing_avoids_current(tmp_path: Path) -> None:
    playlist = _make_playlist(tmp_path, [PlaylistItemStatus.PENDING, PlaylistItemStatus.PENDING])

    decision = decide_next_item(
        playlist,
        panel_selected_indices=[0],
        panel_focus_index=-1,
        ignore_ui_selection=False,
        last_started_item_id="a",
        break_target_index=None,
        restart_playing=True,
        current_playing_item_id="a",
    )

    assert decision.preferred_item_id == "b"
    assert decision.play_index == 1

