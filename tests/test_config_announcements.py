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
