from __future__ import annotations

import pytest

from sara.core.config import SettingsManager


def test_remote_defaults_and_roundtrip(tmp_path):
    path = tmp_path / "settings.yaml"
    settings = SettingsManager(path)
    assert settings.get_remote_enabled() is True
    assert settings.get_remote_port() == 51443
    settings.set_remote_enabled(False)
    settings.set_remote_port(52345)
    settings.save()
    restored = SettingsManager(path)
    assert restored.get_remote_enabled() is False
    assert restored.get_remote_port() == 52345
    assert restored.get_raw()["remote"] == {"enabled": False, "port": 52345}


@pytest.mark.parametrize("value", [0, -1, 65536, None, [], True, 12.5, "invalid"])
def test_bad_config_port_falls_back(tmp_path, value):
    settings = SettingsManager(tmp_path / "settings.yaml")
    settings._data["remote"]["port"] = value
    assert settings.get_remote_port() == 51443
    with pytest.raises(ValueError):
        settings.set_remote_port(value)


@pytest.mark.parametrize("value", [None, [], "invalid"])
def test_malformed_remote_section_can_be_repaired_in_options(tmp_path, value):
    settings = SettingsManager(tmp_path / "settings.yaml")
    settings._data["remote"] = value
    assert settings.get_remote_enabled()
    assert settings.get_remote_port() == 51443
    settings.set_remote_enabled(False)
    settings.set_remote_port(54321)
    assert settings.get_raw()["remote"] == {"enabled": False, "port": 54321}


def test_old_config_uses_remote_defaults(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("general:\n  language: pl\n", encoding="utf-8")
    settings = SettingsManager(path)
    assert settings.get_remote_enabled()
    assert settings.get_remote_port() == 51443
