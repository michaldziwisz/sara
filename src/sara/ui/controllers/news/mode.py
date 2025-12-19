"""Controllers managing edit/read modes for NewsPlaylistPanel."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import wx

from sara.core.i18n import gettext as _
from sara.news.markdown import parse_news_blocks
from sara.news.read_view import ReadViewModel, build_read_view


class NewsEditController:
    """Encapsulates toolbar actions, clipboard handling, and PFL preview in edit mode."""

    def __init__(
        self,
        edit_ctrl: wx.TextCtrl,
        *,
        clipboard_reader: Callable[[], Sequence[str]],
        insert_audio_tokens: Callable[[Sequence[str]], None],
        show_error: Callable[[str], None],
        start_preview: Callable[[Path], bool] | None,
        stop_preview: Callable[[], None] | None,
    ) -> None:
        self._edit_ctrl = edit_ctrl
        self._clipboard_reader = clipboard_reader
        self._insert_tokens = insert_audio_tokens
        self._show_error = show_error
        self._start_preview = start_preview
        self._stop_preview = stop_preview

    def paste_audio_from_clipboard(self, *, silent_if_empty: bool = False) -> bool:
        audio_paths = [Path(path) for path in self._clipboard_reader()]
        valid = [str(path) for path in audio_paths if path.exists()]
        if not valid:
            if not silent_if_empty:
                self._show_error(_("Clipboard does not contain audio files."))
            return False
        self._insert_tokens(valid)
        return True

    def preview_audio_at_caret(self) -> None:
        if not self._start_preview:
            self._show_error(_("Preview is unavailable."))
            return
        placeholder = self._placeholder_at_caret()
        if not placeholder or not placeholder.exists():
            self._show_error(_("Move caret to an audio placeholder to preview."))
            return
        if not self._start_preview(placeholder):
            self._show_error(_("Unable to start audio preview."))

    def stop_preview(self) -> None:
        if self._stop_preview:
            self._stop_preview()

    def _placeholder_at_caret(self) -> Path | None:
        pos = self._edit_ctrl.GetInsertionPoint()
        line_index = self._edit_ctrl.LineFromPosition(pos)
        text = self._edit_ctrl.GetLineText(line_index).strip()
        if not text.startswith("[[audio:") or not text.endswith("]]"):
            return None
        path_value = text[8:-2].strip()
        return Path(path_value) if path_value else None


class NewsReadController:
    """Responsible for building and navigating read-mode content."""

    def __init__(self, get_line_length: Callable[[], int]) -> None:
        self._get_line_length = get_line_length
        self._view: ReadViewModel | None = None

    def build_view(self, markdown: str) -> ReadViewModel:
        blocks = parse_news_blocks(markdown)
        self._view = build_read_view(blocks, self._get_line_length())
        return self._view

    def audio_path_for_line(self, line_index: int) -> str | None:
        view = self._view
        if not view:
            return None
        for marker_line, path in view.audio_markers:
            if marker_line == line_index:
                return path
        return None

    def next_heading_line(self, current_line: int | None, *, direction: int) -> int | None:
        view = self._view
        if not view or not view.heading_lines:
            return None
        reference = self._reference_line(current_line, direction=direction)
        if direction > 0:
            for line in view.heading_lines:
                if line > reference:
                    return line
        else:
            for line in reversed(view.heading_lines):
                if line < reference:
                    return line
        return None

    def next_audio_marker_line(self, current_line: int | None, *, direction: int) -> int | None:
        view = self._view
        if not view or not view.audio_markers:
            return None
        reference = self._reference_line(current_line, direction=direction)
        lines = [line for line, _ in view.audio_markers]
        if direction > 0:
            for line in lines:
                if line > reference:
                    return line
        else:
            for line in reversed(lines):
                if line < reference:
                    return line
        return None

    def handle_key(
        self,
        keycode: int,
        *,
        shift: bool,
        control: bool,
        alt: bool,
        current_line: int | None,
    ) -> "ReadKeyAction":
        """Return action to perform in read mode for a key event."""
        if control or alt:
            return ReadKeyAction()

        if keycode in (_WXK_RETURN, _WXK_NUMPAD_ENTER, _WXK_SPACE):
            path = self.audio_path_for_line(current_line) if current_line is not None else None
            return ReadKeyAction(play_path=path)

        if keycode in (ord("H"), ord("h")):
            target = self.next_heading_line(current_line, direction=-1 if shift else 1)
            return ReadKeyAction(focus_line=target, consumed=target is not None)

        if keycode in (ord("C"), ord("c")):
            target = self.next_audio_marker_line(current_line, direction=-1 if shift else 1)
            return ReadKeyAction(focus_line=target, consumed=target is not None)

        return ReadKeyAction()

    @staticmethod
    def _reference_line(current_line: int | None, *, direction: int) -> int:
        if current_line is not None:
            return current_line
        return -1 if direction > 0 else 10**9


@dataclass(frozen=True)
class ReadKeyAction:
    focus_line: int | None = None
    play_path: str | None = None
    consumed: bool = False

    @property
    def handled(self) -> bool:
        return self.consumed or self.focus_line is not None or self.play_path is not None


_WXK_RETURN = getattr(wx, "WXK_RETURN", 13)
_WXK_NUMPAD_ENTER = getattr(wx, "WXK_NUMPAD_ENTER", _WXK_RETURN)
_WXK_SPACE = getattr(wx, "WXK_SPACE", ord(" "))


__all__ = [
    "NewsEditController",
    "NewsReadController",
    "ReadKeyAction",
]

