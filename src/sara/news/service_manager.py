"""Helpers for loading/saving news service files outside of UI classes."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from sara.core.i18n import gettext as _
from sara.news_service import NewsService, load_news_service, save_news_service


class NewsServiceManager:
    """Encapsulate disk I/O and error reporting for news services."""

    def __init__(
        self,
        *,
        loader: Callable[[Path], NewsService] = load_news_service,
        saver: Callable[[Path, NewsService], None] = save_news_service,
        error_handler: Callable[[str], None] | None = None,
    ) -> None:
        self._loader = loader
        self._saver = saver
        self._error_handler = error_handler or (lambda message: None)

    def __init__(
        self,
        *,
        loader: Callable[[Path], NewsService] = load_news_service,
        saver: Callable[[Path, NewsService], None] = save_news_service,
        error_handler: Callable[[str], None] | None = None,
    ) -> None:
        self._loader = loader
        self._saver = saver
        self._error_handler = error_handler or (lambda message: None)
        self._last_path: Path | None = None

    @property
    def last_path(self) -> Path | None:
        return self._last_path

    def ensure_save_path(self, raw_path: Path) -> Path:
        if raw_path.suffix.lower() != ".saranews":
            raw_path = raw_path.with_suffix(".saranews")
        self._last_path = raw_path
        return raw_path

    def remember_path(self, path: Path) -> None:
        self._last_path = path

    def load_from_path(self, path: Path) -> NewsService | None:
        try:
            return self._loader(path)
        except Exception as exc:  # pylint: disable=broad-except
            self._error_handler(_("Failed to load news service: %s") % exc)
            return None

    def save_to_path(self, target_path: Path, service: NewsService) -> bool:
        try:
            self._saver(target_path, service)
        except Exception as exc:  # pylint: disable=broad-except
            self._error_handler(_("Failed to save news service: %s") % exc)
            return False
        return True
