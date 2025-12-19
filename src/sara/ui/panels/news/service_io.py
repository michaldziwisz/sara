"""News service (load/save) helpers for `NewsPlaylistPanel`."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import wx

from sara.core.i18n import gettext as _
from sara.news.service_manager import NewsServiceManager
from sara.news_service import NewsService
from sara.ui.file_selection_dialog import FileSelectionDialog


_SERVICE_WILDCARD = _("News services (*.saranews)|*.saranews|All files|*.*")


class NewsServiceIO:
    def __init__(
        self,
        parent: wx.Window,
        service_manager: NewsServiceManager,
        *,
        apply_service: Callable[[NewsService], None],
        build_service: Callable[[], NewsService],
    ) -> None:
        self._parent = parent
        self._service_manager = service_manager
        self._apply_service = apply_service
        self._build_service = build_service

    def prompt_load_service(self) -> Path | None:
        dialog = FileSelectionDialog(
            self._parent,
            title=_("Load news service"),
            wildcard=_SERVICE_WILDCARD,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
            start_path=self._service_manager.last_path,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return None
        paths = dialog.get_paths()
        dialog.Destroy()
        if not paths:
            return None
        path = Path(paths[0])
        return path if self.load_service_from_path(path) else None

    def load_service_from_path(self, path: Path) -> bool:
        service = self._service_manager.load_from_path(path)
        if service is None:
            return False
        self._apply_service(service)
        return True

    def prompt_save_service(self) -> Path | None:
        dialog = FileSelectionDialog(
            self._parent,
            title=_("Save news service"),
            wildcard=_SERVICE_WILDCARD,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            start_path=self._service_manager.last_path,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return None
        paths = dialog.get_paths()
        dialog.Destroy()
        if not paths:
            return None
        raw_path = Path(paths[0])
        self._service_manager.remember_path(raw_path)
        target_path = self._service_manager.ensure_save_path(raw_path)
        return target_path if self.save_service_to_path(target_path) else None

    def save_service_to_path(self, target_path: Path) -> bool:
        service = self._build_service()
        return self._service_manager.save_to_path(target_path, service)

