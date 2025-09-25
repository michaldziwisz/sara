from pathlib import Path

from sara.core.announcement_registry import ANNOUNCEMENT_CATEGORIES
from sara.core.config import SettingsManager


def _settings_path(tmp_path: Path) -> Path:
    return tmp_path / "settings.yaml"


def test_announcement_settings_defaults(tmp_path):
    manager = SettingsManager(config_path=_settings_path(tmp_path))
    expected = {
        category.id: category.default_enabled
        for category in ANNOUNCEMENT_CATEGORIES
    }

    assert manager.get_all_announcement_settings() == expected


def test_announcement_settings_persist(tmp_path):
    target_category = ANNOUNCEMENT_CATEGORIES[0].id
    path = _settings_path(tmp_path)

    manager = SettingsManager(config_path=path)
    manager.set_announcement_enabled(target_category, False)
    manager.save()

    reloaded = SettingsManager(config_path=path)

    assert reloaded.get_announcement_enabled(target_category) is False

    for category in ANNOUNCEMENT_CATEGORIES[1:]:
        assert reloaded.get_announcement_enabled(category.id) == category.default_enabled


def test_focus_playing_track_default_false(tmp_path):
    manager = SettingsManager(config_path=_settings_path(tmp_path))

    assert manager.get_focus_playing_track() is False


def test_focus_playing_track_saved_in_accessibility(tmp_path):
    path = _settings_path(tmp_path)
    manager = SettingsManager(config_path=path)
    manager.set_focus_playing_track(True)
    manager.save()

    raw = manager.get_raw()
    accessibility = raw.get("accessibility", {})
    playback = raw.get("playback", {})

    assert accessibility.get("follow_playing_selection") is True
    assert "focus_playing_track" not in playback


def test_focus_playing_track_legacy_false(tmp_path):
    path = _settings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "playback:\n  focus_playing_track: false\n",
        encoding="utf-8",
    )

    manager = SettingsManager(config_path=path)

    assert manager.get_focus_playing_track() is False

    manager.set_focus_playing_track(True)
    manager.save()

    reloaded = SettingsManager(config_path=path)
    assert reloaded.get_focus_playing_track() is True
