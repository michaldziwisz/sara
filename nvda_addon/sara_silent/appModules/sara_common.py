"""NVDA app module that keeps SARA playlists silent by forcing sleep mode."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import api
import core
import inputCore
from appModuleHandler import AppModule
from controlTypes import Role, STATE_SELECTED
from keyboardHandler import KeyboardInputGesture
from logHandler import log
from speech import cancelSpeech
import winUser

_APPDATA = os.environ.get("APPDATA")
_TARGET = Path(_APPDATA or "") / "SARA" / "nvda_sleep_targets.json"
_PLAY_NEXT_SIGNAL = Path(_APPDATA or "") / "SARA" / "nvda_play_next_signal.txt" if _APPDATA else None
_CHECK_INTERVAL_MS = 2000
_PLAYLIST_CLASSES = {"wxWindowNR", "SysListView32"}
_PLAYLIST_SPEECH_WINDOW_MS = 1200
_MANUAL_SPEECH_GESTURE_TIMEOUT_MS = 1500
_PLAY_NEXT_SILENCE_WINDOW_MS = 1200


def _available_role(name: str) -> Role | None:
    return getattr(Role, name, None)


_PLAYLIST_ROLES = {
    role
    for role in map(_available_role, ("PANE", "CLIENT", "WINDOW", "UNKNOWN", "LIST", "LISTITEM"))
    if role is not None
}
def _is_playlist_window(obj: Any) -> bool:
    def _matches(candidate: Any) -> bool:
        try:
            return (
                getattr(candidate, "windowClassName", None) in _PLAYLIST_CLASSES
                and getattr(candidate, "role", None) in _PLAYLIST_ROLES
            )
        except Exception:
            return False

    if obj is None:
        return False
    if _matches(obj):
        return True
    parent = getattr(obj, "parent", None)
    depth = 0
    while parent is not None and depth < 3:
        if _matches(parent):
            return True
        parent = getattr(parent, "parent", None)
        depth += 1
    return False


def _describe_window(obj: Any) -> tuple[str, str]:
    try:
        text = getattr(obj, "name", None) or getattr(obj, "value", None) or ""
    except Exception:
        text = ""
    text_str = str(text)
    reason = "playing" if "; Playing" in text_str else "other"
    return text_str, reason


def _describe_window(obj: Any) -> tuple[str, str]:
    try:
        text = getattr(obj, "name", None) or getattr(obj, "value", None) or ""
    except Exception:
        text = ""
    text_str = str(text)
    reason = "playing" if "; Playing" in text_str else "other"
    return text_str, reason


def _describe_window(obj: Any) -> tuple[str, str]:
    try:
        text = getattr(obj, "name", None) or getattr(obj, "value", None) or ""
    except Exception:
        text = ""
    text_str = str(text)
    reason = "playing" if "; Playing" in text_str else "other"
    return text_str, reason


def _is_playing_entry(obj: Any) -> bool:
    _, reason = _describe_window(obj)
    return reason == "playing"


class AppModule(AppModule):
    sleepMode = False  # keep NVDA fully awake; we mute manually

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._poll_timer = None
        self._playlist_speech_timer = None
        self._playlist_speech_until = 0.0
        self._play_next_silence_until = 0.0
        self._last_mute_details = None
        self._mute_enabled = True
        self._last_play_next_signal_mtime = 0.0
        self._manual_speech_user = False
        self._manual_gesture_until = 0.0
        self._raw_key_handler = inputCore.decide_handleRawKey.register(self._handle_raw_key)
        self._update_mute_state("init")
        self._schedule_poll()
        try:
            log.info("SARA sleep addon init: pid=%s", self.processID)
        except Exception:
            pass

    def event_foreground(self, obj, nextHandler):
        if _is_playlist_window(obj) and self._suppress_event_for_play_next("foreground", obj):
            return
        self._update_mute_state("foreground", obj)
        if nextHandler:
            nextHandler()

    def event_gainFocus(self, obj, nextHandler):
        if _is_playlist_window(obj):
            if self._suppress_event_for_play_next("gainFocus", obj):
                return
            if not self._handle_playlist_event("gainFocus", obj):
                return
        self._update_mute_state("focus", obj)
        if nextHandler:
            nextHandler()

    def event_stateChange(self, obj, nextHandler):
        if _is_playlist_window(obj):
            if not self._handle_playlist_event("stateChange", obj):
                return
        if nextHandler:
            nextHandler()

    def event_selection(self, obj, nextHandler):
        if _is_playlist_window(obj):
            if not self._handle_playlist_event("selection", obj):
                return
        if nextHandler:
            nextHandler()

    def event_selectionAdd(self, obj, nextHandler):
        self.event_selection(obj, nextHandler)

    def event_selectionRemove(self, obj, nextHandler):
        self.event_selection(obj, nextHandler)

    def event_valueChange(self, obj, nextHandler):
        if _is_playlist_window(obj):
            if not self._handle_playlist_event("valueChange", obj):
                return
        if nextHandler:
            nextHandler()

    def terminate(self):
        timer = self._poll_timer
        if timer is not None:
            timer.Stop()
            self._poll_timer = None
        timer = self._playlist_speech_timer
        if timer is not None:
            timer.Stop()
            self._playlist_speech_timer = None
        try:
            inputCore.decide_handleRawKey.unregister(self._handle_raw_key)
        except Exception:
            pass
        super().terminate()

    def _schedule_poll(self) -> None:
        self._poll_timer = core.callLater(_CHECK_INTERVAL_MS, self._poll)

    def _poll(self) -> None:
        self._check_external_play_next_signal()
        self._update_mute_state("poll", api.getFocusObject())
        self._schedule_poll()

    def _update_mute_state(self, source: str, obj: Any | None = None) -> None:
        mute, details = self._should_mute(obj)
        if mute != self._mute_enabled or details != self._last_mute_details:
            self._mute_enabled = mute
            self._last_mute_details = details
            try:
                log.info(
                    "SARA sleep addon %s: pid=%s mute=%s info=%s",
                    source,
                    self.processID,
                    self._mute_enabled,
                    details,
                )
            except Exception:
                pass

    def _should_mute(self, obj: Any | None) -> tuple[bool, str]:
        if not self._is_pid_registered():
            return False, "pid-not-registered"
        now = time.monotonic()
        if self._play_next_silence_until and now < self._play_next_silence_until:
            return True, "play-next-forced"
        obj = obj or api.getFocusObject()
        if not _is_playlist_window(obj):
            return False, f"not-playlist:{getattr(obj, 'windowClassName', None)!r}/{getattr(obj, 'role', None)!r}"
        if self._playlist_speech_until and now < self._playlist_speech_until:
            return False, "arrow-window"
        return True, "playlist"

    def _is_pid_registered(self) -> bool:
        if not _TARGET.exists():
            return False
        try:
            data = json.loads(_TARGET.read_text(encoding="utf-8"))
        except Exception:
            return False
        pids = data.get("pids", [])
        registered = self.processID in pids
        if not registered:
            try:
                log.info("SARA sleep addon pid %s missing in registry %s", self.processID, pids)
            except Exception:
                pass
        return registered

    def _is_play_next_silence_active(self) -> bool:
        return bool(self._play_next_silence_until and time.monotonic() < self._play_next_silence_until)

    def _is_manual_speech_active(self) -> bool:
        return bool(self._playlist_speech_until and time.monotonic() < self._playlist_speech_until)

    def _refresh_manual_speech_window(self, obj: Any) -> bool:
        if not self._is_manual_speech_active():
            return False
        if not self._manual_speech_user:
            return False
        self._allow_playlist_speech_window(obj)
        return True

    def _allow_playlist_speech_window(self, obj: Any, *, force: bool = False) -> None:
        if not force and self._is_play_next_silence_active():
            try:
                log.info(
                    "SARA sleep addon speech window skipped (play-next silence) focus=%s/%s",
                    getattr(obj, "windowClassName", None),
                    getattr(obj, "role", None),
                )
            except Exception:
                pass
            return
        try:
            log.info(
                "SARA sleep addon speech window focus=%s/%s",
                getattr(obj, "windowClassName", None),
                getattr(obj, "role", None),
            )
        except Exception:
            pass
        self._playlist_speech_until = time.monotonic() + (_PLAYLIST_SPEECH_WINDOW_MS / 1000)
        timer = self._playlist_speech_timer
        if timer is not None:
            timer.Stop()
        self._playlist_speech_timer = core.callLater(
            _PLAYLIST_SPEECH_WINDOW_MS, self._end_playlist_speech_window
        )
        if force:
            self._manual_speech_user = True
            self._manual_gesture_until = time.monotonic() + (
                _MANUAL_SPEECH_GESTURE_TIMEOUT_MS / 1000
            )
        self._update_mute_state("arrow", obj)

    def _end_playlist_speech_window(self) -> None:
        timer = self._playlist_speech_timer
        if timer is not None:
            try:
                timer.Stop()
            except Exception:
                pass
        self._playlist_speech_timer = None
        self._playlist_speech_until = 0.0
        self._manual_speech_user = False
        self._manual_gesture_until = 0.0
        self._update_mute_state("arrow-expire")

    def _trigger_playback_silence(self, reason: str, obj: Any | None) -> None:
        self._play_next_silence_until = time.monotonic() + (_PLAY_NEXT_SILENCE_WINDOW_MS / 1000)
        self._end_playlist_speech_window()
        cancelSpeech()
        self._update_mute_state(reason, obj)

    def _speak_current_playlist_item(self) -> None:
        for name in ("kb(desktop):NVDA+tab", "kb:NVDA+tab"):
            try:
                gesture = KeyboardInputGesture.fromName(name)
            except Exception:
                continue
            try:
                log.info("SARA sleep addon announcing current playlist item via %s", name)
            except Exception:
                pass
            try:
                gesture.send()
            except Exception:
                continue
            break

    def _cancel_play_next_silence(self, source: str) -> None:
        if not self._play_next_silence_until:
            return
        self._play_next_silence_until = 0.0
        try:
            log.info("SARA sleep addon play-next silence canceled: %s", source)
        except Exception:
            pass
        self._update_mute_state(source + "-cancel")

    def _handle_raw_key(self, vkCode, scanCode, extended, pressed):
        if not pressed:
            return True
        obj = api.getFocusObject()
        if not _is_playlist_window(obj):
            return True
        if vkCode in (winUser.VK_UP, winUser.VK_DOWN):
            self._cancel_play_next_silence("arrow-override")
            self._allow_playlist_speech_window(obj, force=True)
            self._speak_current_playlist_item()
        elif vkCode in (winUser.VK_SPACE, winUser.VK_F1):
            self._trigger_playback_silence("play-next", obj)
        return True

    def _handle_playlist_event(self, event_name: str, obj: Any) -> bool:
        self._check_external_play_next_signal()
        self._log_event(event_name, obj)
        if self._suppress_event_for_play_next(event_name, obj):
            return False
        if self._is_manual_speech_active():
            if not self._manual_speech_user:
                return False
            now = time.monotonic()
            if now >= self._manual_gesture_until:
                self._manual_speech_user = False
                self._manual_gesture_until = 0.0
                return False
            if not self._refresh_manual_speech_window(obj):
                return False
            self._manual_speech_user = False
            self._manual_gesture_until = 0.0
            return True
        cancelSpeech()
        self._update_mute_state(f"{event_name}-auto", obj)
        return False

    def _check_external_play_next_signal(self) -> None:
        if _PLAY_NEXT_SIGNAL is None:
            return
        try:
            mtime = _PLAY_NEXT_SIGNAL.stat().st_mtime
        except FileNotFoundError:
            return
        except OSError:
            return
        if mtime <= self._last_play_next_signal_mtime:
            return
        self._last_play_next_signal_mtime = mtime
        try:
            log.info("SARA sleep addon external play-next signal detected")
        except Exception:
            pass
        self._trigger_playback_silence("play-next-signal", api.getFocusObject())

    def _suppress_event_for_play_next(self, event_name: str, obj: Any) -> bool:
        if not self._is_play_next_silence_active():
            return False
        _, reason = _describe_window(obj)
        if reason != "playing" and event_name != "valueChange":
            return False
        try:
            log.info(
                "SARA sleep addon suppressing %s during play-next focus=%s/%s",
                event_name,
                getattr(obj, "windowClassName", None),
                getattr(obj, "role", None),
            )
        except Exception:
            pass
        cancelSpeech()
        self._update_mute_state(f"{event_name}-suppressed", obj)
        return True

    @staticmethod
    def _log_event(name: str, obj: Any) -> None:
        try:
            text, _ = _describe_window(obj)
            log.info(
                "SARA sleep addon %s focus=%s/%s text=%s",
                name,
                getattr(obj, "windowClassName", None),
                getattr(obj, "role", None),
                text,
            )
        except Exception:
            pass
