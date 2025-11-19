from __future__ import annotations

from pathlib import Path
from typing import List

from sara.core.config import SettingsManager
from sara.ui.announcement_service import AnnouncementService


def _settings(tmp_path) -> SettingsManager:
    return SettingsManager(config_path=tmp_path / "settings.yaml")


def test_announcement_respects_category_flags(tmp_path):
    settings = _settings(tmp_path)
    status: List[str] = []
    spoken: List[str] = []

    service = AnnouncementService(
        settings,
        status_callback=status.append,
        speak_fn=lambda msg: spoken.append(msg) or True,
        cancel_fn=lambda: spoken.append("CANCEL") or True,
    )

    service.announce("general", "Hello")
    assert status == ["Hello"]
    assert spoken == ["Hello"]

    settings.set_announcement_enabled("general", False)
    service.announce("general", "Muted")
    assert spoken == ["Hello"]


def test_announcement_silence_and_empty_spoken(tmp_path):
    settings = _settings(tmp_path)
    spoken: List[str] = []
    service = AnnouncementService(
        settings,
        status_callback=None,
        speak_fn=lambda msg: spoken.append(msg) or True,
        cancel_fn=lambda: spoken.append("CANCEL") or True,
    )
    service.announce("general", "First")
    service.announce("general", "stop", spoken_message="")
    service.silence()
    assert spoken == ["First", "CANCEL", "CANCEL"]
