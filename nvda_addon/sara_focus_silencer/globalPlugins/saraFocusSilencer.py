"""NVDA global plugin that silences focus speech when SARA is active."""

from __future__ import annotations

import api
import globalPluginHandler
import speech
import wx
from controlTypes import REASON_FOCUS
from logHandler import log

# Fallback int constants in case speech exposes enums differently across NVDA versions.
SPEECH_MODE_OFF = getattr(speech, "SpeechMode", None)
if SPEECH_MODE_OFF is not None:
    SPEECH_MODE_OFF = speech.SpeechMode.off
else:
    SPEECH_MODE_OFF = 0

try:
    _get_speech_mode = speech.getSpeechMode
    _set_speech_mode = speech.setSpeechMode
except AttributeError:
    _get_speech_mode = None
    _set_speech_mode = None


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    """Silence NVDA focus announcements for the SARA application."""

    def __init__(self) -> None:
        super().__init__()
        self._restore_mode: int | None = None
        self._restore_timer: wx.CallLater | None = None

    def terminate(self) -> None:  # type: ignore[override]
        self._restore_speech(force=True)
        super().terminate()

    def event_gainFocus(self, obj, nextHandler):  # type: ignore[override]
        if self._belongs_to_sara(obj):
            self._suspend_speech()
            try:
                nextHandler()
            finally:
                self._schedule_restore()
        else:
            self._restore_speech(force=False)
            nextHandler()

    def script_announceSaraFocus(self, gesture) -> None:
        focus = api.getFocusObject()
        if not self._belongs_to_sara(focus):
            # Fall back to NVDA's default announcement outside of SARA.
            speech.speakObjectProperties(focus, reason=REASON_FOCUS)
            return

        self._restore_speech(force=True)
        speech.speakObjectProperties(focus, reason=REASON_FOCUS)

    __gestures = {
        "kb:NVDA+shift+i": "announceSaraFocus",
    }

    def _belongs_to_sara(self, obj) -> bool:
        try:
            app_mod = obj.appModule
        except AttributeError:
            app_mod = None

        if app_mod:
            app_name = (getattr(app_mod, "appName", "") or "").lower()
            product_name = (getattr(app_mod, "productName", "") or "").lower()
            if "sara" in product_name or app_name == "sara":
                return True

        try:
            foreground = api.getForegroundObject()
            if foreground:
                title = (foreground.name or "").lower()
                if title.startswith("sara"):
                    return True
        except Exception:  # pragma: no cover - defensive
            log.debug("SARA silencer: unable to inspect foreground window", exc_info=True)

        return False

    def _suspend_speech(self) -> None:
        if _get_speech_mode is None or _set_speech_mode is None:
            speech.cancelSpeech()
            return

        if self._restore_timer is not None:
            self._restore_timer.Stop()
            self._restore_timer = None

        if self._restore_mode is None:
            current_mode = _get_speech_mode()
            if current_mode == SPEECH_MODE_OFF:
                return
            if _set_speech_mode(SPEECH_MODE_OFF):
                self._restore_mode = current_mode

    def _schedule_restore(self) -> None:
        if _set_speech_mode is None:
            return
        if self._restore_mode is None:
            return
        if self._restore_timer is not None:
            self._restore_timer.Stop()
        self._restore_timer = wx.CallLater(250, self._restore_speech, True)

    def _restore_speech(self, force: bool) -> None:
        if _set_speech_mode is None:
            return
        if self._restore_timer is not None:
            self._restore_timer.Stop()
            self._restore_timer = None
        if self._restore_mode is None and not force:
            return
        mode = self._restore_mode if self._restore_mode is not None else _get_speech_mode()
        if mode is not None and mode != SPEECH_MODE_OFF:
            _set_speech_mode(mode)
        self._restore_mode = None
