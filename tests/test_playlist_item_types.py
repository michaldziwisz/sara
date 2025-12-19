from __future__ import annotations

from pathlib import Path

from sara.core.app_state import PlaylistFactory
from sara.core.config import SettingsManager
from sara.core.playlist import PlaylistItem, PlaylistItemType, PlaylistKind, PlaylistModel
from sara.ui.controllers.playlists.clipboard import create_item_from_serialized, serialize_items
from sara.ui.controllers.playlists.item_types import apply_item_type_to_selection


def test_playlist_item_defaults_to_song() -> None:
    item = PlaylistItem(id="one", path=Path("a.mp3"), title="A", duration_seconds=1.0)
    assert item.item_type is PlaylistItemType.SONG


def test_clipboard_serialization_round_trip_preserves_item_type() -> None:
    item = PlaylistItem(
        id="one",
        path=Path("a.mp3"),
        title="A",
        duration_seconds=1.0,
        item_type=PlaylistItemType.SPOT,
    )
    serialized = serialize_items([item])[0]

    class _Frame:
        _playlist_factory = PlaylistFactory()

    restored = create_item_from_serialized(_Frame(), serialized)
    assert restored.item_type is PlaylistItemType.SPOT


def test_settings_default_shortcuts_include_item_type_actions(tmp_path: Path) -> None:
    manager = SettingsManager(config_path=tmp_path / "settings.yaml")
    assert manager.get_shortcut("edit", "mark_as_song") == "CTRL+SHIFT+G"
    assert manager.get_shortcut("edit", "mark_as_spot") == "CTRL+SHIFT+S"


def test_apply_item_type_to_selection_marks_selected_items() -> None:
    model = PlaylistModel(
        id="pl",
        name="Test",
        kind=PlaylistKind.MUSIC,
        items=[
            PlaylistItem(id="a", path=Path("a.mp3"), title="A", duration_seconds=1.0),
            PlaylistItem(id="b", path=Path("b.mp3"), title="B", duration_seconds=1.0),
        ],
    )

    class _Panel:
        def __init__(self) -> None:
            self.model = model
            self._selected = [1]
            self.refreshed: list[tuple[list[int] | None, bool]] = []

        def get_selected_indices(self) -> list[int]:
            return list(self._selected)

        def get_focused_index(self) -> int:
            return -1

        def set_selection(self, indices: list[int], *, focus: bool = True) -> None:
            self._selected = list(indices)

        def refresh(self, selected_indices: list[int] | None = None, *, focus: bool = True) -> None:
            self.refreshed.append((selected_indices, bool(focus)))

    panel = _Panel()

    class _Frame:
        def __init__(self) -> None:
            self.announced: list[tuple[str, str]] = []

        def _get_audio_panel(self, kinds) -> _Panel | None:
            return panel if panel.model.kind in kinds else None

        def _announce_event(self, category: str, message: str, **_kwargs) -> None:
            self.announced.append((category, message))

    frame = _Frame()
    apply_item_type_to_selection(frame, PlaylistItemType.SPOT)

    assert model.items[0].item_type is PlaylistItemType.SONG
    assert model.items[1].item_type is PlaylistItemType.SPOT
    assert panel.refreshed == [([1], True)]
    assert frame.announced

