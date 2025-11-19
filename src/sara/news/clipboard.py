"""Helpers for extracting audio file paths from clipboard (used in edit mode)."""

from __future__ import annotations

import ctypes
from pathlib import Path
from typing import Iterable, List

import wx

from sara.core.media_metadata import is_supported_audio_file


def clipboard_audio_paths() -> list[str]:
    """Return supported audio files from clipboard (text paths, drag&drop, etc.)."""

    candidates = _collect_clipboard_strings()
    candidates.extend(_collect_win32_file_drops())
    if not candidates:
        return []

    audio_files: list[str] = []
    for candidate in candidates:
        _collect_from_path(candidate, audio_files)
    return audio_files


def _collect_clipboard_strings() -> list[str]:
    clipboard = wx.TheClipboard
    if not clipboard.Open():
        return []
    candidates: list[str] = []
    try:
        file_data = wx.FileDataObject()
        if clipboard.GetData(file_data):
            candidates.extend(file_data.GetFilenames())
        text_data = wx.TextDataObject()
        if clipboard.GetData(text_data):
            for raw_entry in text_data.GetText().splitlines():
                entry = raw_entry.strip().strip('"')
                if entry:
                    candidates.append(entry)
    finally:
        clipboard.Close()
    return candidates


def _collect_win32_file_drops() -> list[str]:
    if not hasattr(ctypes, "windll"):
        return []
    CF_HDROP = 15
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    if not user32.OpenClipboard(0):
        return []
    filenames: list[str] = []
    try:
        if not user32.IsClipboardFormatAvailable(CF_HDROP):
            return []
        hdrop = user32.GetClipboardData(CF_HDROP)
        if not hdrop:
            return []
        count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
        buffer = ctypes.create_unicode_buffer(260)
        for index in range(count):
            length = shell32.DragQueryFileW(hdrop, index, buffer, len(buffer))
            if length:
                filenames.append(buffer.value)
    finally:
        user32.CloseClipboard()
    return filenames


def _collect_from_path(raw: str, bucket: list[str]) -> None:
    target = Path(raw.replace("\\\\?\\", "")).expanduser()
    if not target.exists():
        return
    if target.is_dir():
        for file_path in sorted(target.rglob("*")):
            if file_path.is_file() and is_supported_audio_file(file_path):
                bucket.append(str(file_path))
        return
    if is_supported_audio_file(target):
        bucket.append(str(target))

