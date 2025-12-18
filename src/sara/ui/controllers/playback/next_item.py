"""Next item selection logic for the playback flow.

Extracted from `sara.ui.controllers.playback_flow.start_next_from_playlist` so
the selection rules are easier to read and unit-test.
"""

from __future__ import annotations

from dataclasses import dataclass

from sara.core.playlist import PlaylistItemStatus, PlaylistKind, PlaylistModel


@dataclass(frozen=True)
class NextItemDecision:
    preferred_item_id: str | None
    play_index: int | None
    used_ui_selection: bool
    consumed_model_selection: bool


def _index_of_item(playlist: PlaylistModel, item_id: str | None) -> int | None:
    if not item_id:
        return None
    for idx, item in enumerate(playlist.items):
        if item.id == item_id:
            return idx
    return None


def _derive_next_play_index(playlist: PlaylistModel, last_started_item_id: str | None) -> int | None:
    if not playlist.items:
        return None
    if not last_started_item_id:
        return 0
    last_index = _index_of_item(playlist, last_started_item_id)
    if last_index is None:
        return 0
    return (last_index + 1) % len(playlist.items)


def _next_pending_or_paused(playlist: PlaylistModel, start_idx: int) -> int | None:
    for idx in range(start_idx, len(playlist.items)):
        if playlist.items[idx].status in (PlaylistItemStatus.PENDING, PlaylistItemStatus.PAUSED):
            return idx
    return None


def _next_pending(playlist: PlaylistModel, start_idx: int) -> int | None:
    for idx in range(start_idx, len(playlist.items)):
        if playlist.items[idx].status is PlaylistItemStatus.PENDING:
            return idx
    return None


def decide_next_item(
    playlist: PlaylistModel,
    *,
    panel_selected_indices: list[int],
    panel_focus_index: int,
    ignore_ui_selection: bool,
    last_started_item_id: str | None,
    break_target_index: int | None,
    restart_playing: bool,
    current_playing_item_id: str | None,
) -> NextItemDecision:
    consumed_model_selection = False
    preferred_item_id = playlist.next_selected_item_id()
    play_index: int | None = None
    used_ui_selection = False

    if preferred_item_id:
        consumed_model_selection = True
        play_index = _index_of_item(playlist, preferred_item_id)
    else:
        if break_target_index is not None:
            play_index = _next_pending(playlist, break_target_index)

        if play_index is None and playlist.kind is PlaylistKind.MUSIC:
            if last_started_item_id:
                last_idx = _index_of_item(playlist, last_started_item_id)
                last_item = playlist.get_item(last_started_item_id)
                if last_idx is not None and last_item and last_item.status is PlaylistItemStatus.PLAYED:
                    play_index = _next_pending(playlist, last_idx + 1)

        if play_index is None:
            if not ignore_ui_selection:
                eligible_ui_selection = [
                    idx
                    for idx in panel_selected_indices
                    if 0 <= idx < len(playlist.items)
                    and playlist.items[idx].status in (PlaylistItemStatus.PENDING, PlaylistItemStatus.PAUSED)
                ]
            else:
                eligible_ui_selection = []

            if eligible_ui_selection:
                play_index = eligible_ui_selection[0]
                used_ui_selection = True
            elif not ignore_ui_selection:
                focus_index = panel_focus_index
                if focus_index != -1 and 0 <= focus_index < len(playlist.items):
                    focus_item = playlist.items[focus_index]
                    if focus_item.status in (PlaylistItemStatus.PENDING, PlaylistItemStatus.PAUSED):
                        play_index = focus_index
                        used_ui_selection = True
                    else:
                        play_index = _derive_next_play_index(playlist, last_started_item_id)
                else:
                    play_index = _derive_next_play_index(playlist, last_started_item_id)
            else:
                play_index = _derive_next_play_index(playlist, last_started_item_id)

        if play_index is not None and 0 <= play_index < len(playlist.items):
            preferred_item_id = playlist.items[play_index].id
        else:
            preferred_item_id = None

    if play_index is not None and not (
        0 <= play_index < len(playlist.items)
        and playlist.items[play_index].status in (PlaylistItemStatus.PENDING, PlaylistItemStatus.PAUSED)
    ):
        play_index = _next_pending_or_paused(playlist, play_index + 1)
        preferred_item_id = playlist.items[play_index].id if play_index is not None else None

    if restart_playing and current_playing_item_id and preferred_item_id == current_playing_item_id:
        play_index = _derive_next_play_index(playlist, last_started_item_id)
        preferred_item_id = playlist.items[play_index].id if play_index is not None else None
        consumed_model_selection = False

    return NextItemDecision(
        preferred_item_id=preferred_item_id,
        play_index=play_index,
        used_ui_selection=used_ui_selection,
        consumed_model_selection=consumed_model_selection,
    )
