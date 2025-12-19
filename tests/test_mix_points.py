from __future__ import annotations

from pathlib import Path

from sara.core.mix_points import propagate_mix_points_for_path
from sara.core.playlist import PlaylistItem, PlaylistKind, PlaylistModel


def test_propagate_mix_points_for_path_updates_duplicates_only(tmp_path: Path):
    path = tmp_path / "dup.wav"
    path.write_text("x")

    playlist1 = PlaylistModel(id="pl-1", name="P1", kind=PlaylistKind.MUSIC)
    source = PlaylistItem(id="src", path=path, title="Source", duration_seconds=10.0, cue_in_seconds=9.0)
    dup_same_playlist = PlaylistItem(id="dup-1", path=path, title="Dup1", duration_seconds=10.0)
    playlist1.add_items([source, dup_same_playlist])

    playlist2 = PlaylistModel(id="pl-2", name="P2", kind=PlaylistKind.MUSIC)
    dup_other_playlist = PlaylistItem(id="dup-2", path=path, title="Dup2", duration_seconds=10.0, segue_seconds=1.0)
    playlist2.add_items([dup_other_playlist])

    mix_values = {
        "cue_in": 1.0,
        "intro": 2.0,
        "outro": 8.0,
        "segue": 6.0,
        "segue_fade": 0.5,
        "overlap": 1.5,
    }

    updated = propagate_mix_points_for_path(
        [playlist1, playlist2],
        path=path,
        mix_values=mix_values,
        source_playlist_id=playlist1.id,
        source_item_id=source.id,
    )

    assert set(updated.keys()) == {playlist1.id, playlist2.id}
    assert updated[playlist1.id] == [dup_same_playlist.id]
    assert updated[playlist2.id] == [dup_other_playlist.id]

    # source item should stay untouched
    assert source.cue_in_seconds == 9.0

    assert dup_same_playlist.cue_in_seconds == 1.0
    assert dup_same_playlist.intro_seconds == 2.0
    assert dup_same_playlist.outro_seconds == 8.0
    assert dup_same_playlist.segue_seconds == 6.0
    assert dup_same_playlist.segue_fade_seconds == 0.5
    assert dup_same_playlist.overlap_seconds == 1.5

    assert dup_other_playlist.segue_seconds == 6.0

    # second run should report no changes
    updated_again = propagate_mix_points_for_path(
        [playlist1, playlist2],
        path=path,
        mix_values=mix_values,
        source_playlist_id=playlist1.id,
        source_item_id=source.id,
    )
    assert updated_again == {}

