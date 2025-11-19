"""Utility for announcing status updates and screen reader output."""

from __future__ import annotations

from typing import Callable

from sara.core.config import SettingsManager
from sara.ui.speech import cancel_speech, speak_text


class AnnouncementService:
    """Centralised handler for status bar text and screen reader announcements."""

    def __init__(
        self,
        settings: SettingsManager,
        *,
        status_callback: Callable[[str], None] | None = None,
        speak_fn: Callable[[str], bool] = speak_text,
        cancel_fn: Callable[[], bool] = cancel_speech,
    ) -> None:
        self._settings = settings
        self._set_status = status_callback
        self._speak = speak_fn
        self._cancel = cancel_fn

    def announce(self, category: str, message: str, *, spoken_message: str | None = None) -> None:
        if self._set_status:
            self._set_status(message)
        if not self._settings.get_announcement_enabled(category):
            return
        if spoken_message == "":
            self._cancel()
            return
        self._speak(spoken_message if spoken_message is not None else message)

    def silence(self) -> None:
        self._cancel()

