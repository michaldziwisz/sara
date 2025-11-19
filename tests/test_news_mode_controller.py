from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.append("src")

if "wx" not in sys.modules:
    sys.modules["wx"] = types.SimpleNamespace(TextCtrl=object)

from sara.ui.news_mode_controller import NewsEditController, NewsReadController


class _FakeTextCtrl:
    def __init__(self, lines: list[str], caret_line: int = 0) -> None:
        self._lines = lines
        self._caret_line = caret_line

    def GetInsertionPoint(self) -> int:  # noqa: N802
        return self._caret_line

    def LineFromPosition(self, pos: int) -> int:  # noqa: N802
        return pos

    def GetLineText(self, line_index: int) -> str:  # noqa: N802
        return self._lines[line_index]

    def set_caret_line(self, line_index: int) -> None:
        self._caret_line = line_index


def _build_controller(markdown: str) -> tuple[NewsReadController, list[int], list[tuple[int, str]]]:
    controller = NewsReadController(lambda: 120)
    view = controller.build_view(markdown)
    return controller, view.heading_lines, view.audio_markers


def test_heading_navigation_respects_direction() -> None:
    controller, heading_lines, _ = _build_controller("# H1\n\n## H2\n\n### H3")
    h1, h2, h3 = heading_lines

    assert controller.next_heading_line(None, direction=1) == h1
    assert controller.next_heading_line(h1, direction=1) == h2
    assert controller.next_heading_line(h2, direction=1) == h3
    assert controller.next_heading_line(h3, direction=1) is None

    assert controller.next_heading_line(None, direction=-1) == h3
    assert controller.next_heading_line(h3, direction=-1) == h2
    assert controller.next_heading_line(h2, direction=-1) == h1
    assert controller.next_heading_line(h1, direction=-1) is None


def test_audio_marker_navigation_and_lookup() -> None:
    controller, _, audio_markers = _build_controller(
        "# Title\n\n[[audio:/clip1.wav]]\n\nParagraph\n\n[[audio:/clip2.wav]]"
    )
    first_line, first_path = audio_markers[0]
    second_line, second_path = audio_markers[1]

    assert controller.audio_path_for_line(first_line) == first_path
    assert controller.audio_path_for_line(first_line + 1) is None

    assert controller.next_audio_marker_line(None, direction=1) == first_line
    assert controller.next_audio_marker_line(first_line, direction=1) == second_line
    assert controller.next_audio_marker_line(second_line, direction=1) is None

    assert controller.next_audio_marker_line(None, direction=-1) == second_line
    assert controller.next_audio_marker_line(second_line, direction=-1) == first_line
    assert controller.next_audio_marker_line(first_line, direction=-1) is None


def test_handle_key_returns_navigation_actions() -> None:
    controller, heading_lines, audio_markers = _build_controller(
        "# One\n\n## Two\n\n[[audio:/clip.wav]]\n\nParagraph"
    )
    h1, h2 = heading_lines
    audio_line, audio_path = audio_markers[0]

    heading_action = controller.handle_key(ord("H"), shift=False, control=False, alt=False, current_line=h1)
    assert heading_action.focus_line == h2
    assert heading_action.handled

    heading_prev = controller.handle_key(ord("h"), shift=True, control=False, alt=False, current_line=h2)
    assert heading_prev.focus_line == h1

    play_action = controller.handle_key(ord(" "), shift=False, control=False, alt=False, current_line=audio_line)
    assert play_action.play_path == audio_path
    assert play_action.handled


def test_paste_audio_from_clipboard_inserts_only_existing(tmp_path: Path) -> None:
    existing = tmp_path / "clip.wav"
    existing.write_bytes(b"data")
    missing = tmp_path / "missing.wav"

    captured: list[list[str]] = []
    controller = NewsEditController(
        _FakeTextCtrl([""]),
        clipboard_reader=lambda: [str(existing), str(missing)],
        insert_audio_tokens=lambda tokens: captured.append(list(tokens)),
        show_error=lambda _msg: (_ for _ in ()).throw(AssertionError("should not error")),
        start_preview=None,
        stop_preview=None,
    )

    controller.paste_audio_from_clipboard()
    assert captured == [[str(existing)]]


def test_paste_audio_from_clipboard_shows_error_when_empty() -> None:
    errors: list[str] = []
    controller = NewsEditController(
        _FakeTextCtrl([""]),
        clipboard_reader=lambda: [],
        insert_audio_tokens=lambda _tokens: (_ for _ in ()).throw(AssertionError("should not insert")),
        show_error=errors.append,
        start_preview=None,
        stop_preview=None,
    )

    controller.paste_audio_from_clipboard()
    assert errors and "Clipboard" in errors[0]


def test_preview_requires_placeholder_and_existing_file(tmp_path: Path) -> None:
    clip = tmp_path / "audio.mp3"
    clip.write_bytes(b"x")

    ctrl = _FakeTextCtrl(["[[audio:%s]]" % clip])
    previewed: list[Path] = []
    errors: list[str] = []

    controller = NewsEditController(
        ctrl,
        clipboard_reader=lambda: [],
        insert_audio_tokens=lambda _tokens: None,
        show_error=errors.append,
        start_preview=lambda path: previewed.append(path) or True,
        stop_preview=None,
    )

    controller.preview_audio_at_caret()
    assert previewed == [clip]
    assert not errors


def test_preview_reports_errors_on_missing_placeholder_or_failure(tmp_path: Path) -> None:
    clip = tmp_path / "audio.mp3"
    clip.write_bytes(b"x")
    ctrl = _FakeTextCtrl(["Paragraph"])
    errors: list[str] = []

    controller = NewsEditController(
        ctrl,
        clipboard_reader=lambda: [],
        insert_audio_tokens=lambda _tokens: None,
        show_error=errors.append,
        start_preview=lambda _path: False,
        stop_preview=None,
    )

    controller.preview_audio_at_caret()
    assert errors  # no placeholder

    ctrl.set_caret_line(0)
    ctrl._lines = ["[[audio:%s]]" % clip]
    errors.clear()
    controller.preview_audio_at_caret()
    assert errors  # start_preview returned False
