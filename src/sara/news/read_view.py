"""Helpers for building the read-mode view for news playlists."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Sequence

from sara.core.i18n import gettext as _
from sara.news.markdown import NewsBlock, wrap_news_text


@dataclass(frozen=True)
class ReadViewModel:
    lines: List[str]
    heading_lines: List[int]
    audio_markers: List[tuple[int, str]]
    audio_paths: List[str]


def build_read_view(
    blocks: Sequence[NewsBlock],
    line_length: int,
    *,
    audio_label_factory: Callable[[Path], str] | None = None,
) -> ReadViewModel:
    """Convert parsed blocks into wrapped lines and metadata for read mode."""

    article_lines: list[str] = []
    heading_lines: list[int] = []
    audio_markers: list[tuple[int, str]] = []
    audio_entries: list[str] = []

    label_factory = audio_label_factory or (lambda path: _("(Audio clip: %s)") % path.name)

    for block in blocks:
        btype = block.kind
        if btype in {"paragraph", "list", "heading"}:
            text = block.text or ""
            prefix = ""
            if btype == "list":
                prefix = "- "
            if btype == "heading":
                level = block.level or 1
                prefix = "#" * level + " "
                heading_lines.append(len(article_lines))
            lines = wrap_news_text(prefix + text, line_length)
            if article_lines and article_lines[-1] != "":
                article_lines.append("")
            article_lines.extend(lines)
        elif btype == "audio":
            path_str = block.path or ""
            path = Path(path_str)
            label = label_factory(path)
            line_index = len(article_lines)
            article_lines.append(label)
            audio_markers.append((line_index, path_str))
            audio_entries.append(path_str)
        if article_lines and article_lines[-1] != "":
            article_lines.append("")

    if article_lines and article_lines[-1] == "":
        article_lines.pop()

    return ReadViewModel(
        lines=article_lines,
        heading_lines=heading_lines,
        audio_markers=audio_markers,
        audio_paths=audio_entries,
    )
