from pathlib import Path

import pytest

from sara.news.service_manager import NewsServiceManager
from sara.news_service import NewsService


def test_ensure_save_path_adds_extension(tmp_path):
    manager = NewsServiceManager()
    base = tmp_path / "service"
    assert manager.ensure_save_path(base).suffix == ".saranews"
    already = tmp_path / "ready.saranews"
    assert manager.ensure_save_path(already) == already


def test_load_reports_errors(monkeypatch, tmp_path):
    messages = []

    def fake_loader(_path: Path) -> NewsService:
        raise RuntimeError("boom")

    manager = NewsServiceManager(loader=fake_loader, error_handler=messages.append)
    assert manager.load_from_path(tmp_path / "missing.saranews") is None
    assert "Failed to load" in messages[0]


def test_save_reports_errors(tmp_path):
    messages = []
    service = NewsService(title="Test", markdown="", output_device=None, line_length=30)

    def fake_saver(_path: Path, _service: NewsService) -> None:
        raise IOError("disk full")

    manager = NewsServiceManager(saver=fake_saver, error_handler=messages.append)
    assert manager.save_to_path(tmp_path / "service.saranews", service) is False
    assert "Failed to save" in messages[0]
