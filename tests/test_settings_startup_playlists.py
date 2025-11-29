from pathlib import Path

from sara.core.config import SettingsManager
from sara.core.playlist import PlaylistKind


def test_startup_playlist_folder_roundtrip(tmp_path):
    config_path = tmp_path / "settings.yaml"
    manager = SettingsManager(config_path=config_path)
    music_folder = tmp_path / "library"
    music_folder.mkdir()
    manager.set_startup_playlists(
        [
            {
                "name": "Library",
                "slots": [],
                "kind": PlaylistKind.FOLDER,
                "folder_path": music_folder,
            }
        ]
    )
    manager.save()

    reloaded = SettingsManager(config_path=config_path)
    playlists = reloaded.get_startup_playlists()
    assert len(playlists) == 1
    entry = playlists[0]
    assert entry["kind"] is PlaylistKind.FOLDER
    assert entry["folder_path"] == music_folder
