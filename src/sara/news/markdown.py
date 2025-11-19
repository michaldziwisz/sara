"""Helpers for parsing and wrapping news playlist markdown content."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal


NewsBlockType = Literal["paragraph", "heading", "list", "audio"]


@dataclass(frozen=True, slots=True)
class NewsBlock:
    """Logical block extracted from the news editor markdown."""

    kind: NewsBlockType
    text: str | None = None
    level: int | None = None
    path: str | None = None


_AUDIO_TOKEN = re.compile(r"\[\[audio:(.+?)\]\]")
_HEADING_TOKEN = re.compile(r"^(#{1,5})\s+(.*)")


def parse_news_blocks(text: str) -> list[NewsBlock]:
    """Split markdown-ish content into logical blocks for rendering."""

    lines = text.splitlines()
    blocks: list[NewsBlock] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(NewsBlock(kind="paragraph", text="\n".join(paragraph)))
            paragraph.clear()

    for raw_line in lines:
        stripped = raw_line.strip()
        audio_match = _AUDIO_TOKEN.fullmatch(stripped)
        if audio_match:
            flush_paragraph()
            blocks.append(NewsBlock(kind="audio", path=audio_match.group(1).strip()))
            continue
        if not stripped:
            flush_paragraph()
            continue
        heading_match = _HEADING_TOKEN.match(stripped)
        if heading_match:
            flush_paragraph()
            level = len(heading_match.group(1))
            text_value = heading_match.group(2).strip()
            blocks.append(NewsBlock(kind="heading", text=text_value, level=level))
            continue
        if stripped.startswith(("- ", "* ")):
            flush_paragraph()
            blocks.append(NewsBlock(kind="list", text=stripped[2:].strip()))
            continue
        paragraph.append(stripped)

    flush_paragraph()
    return blocks


def wrap_news_text(text: str, line_length: int) -> list[str]:
    """Wrap long text while respecting word boundaries."""

    if line_length <= 0:
        return [text]

    segments = text.split("\n")
    lines: list[str] = []
    for segment in segments:
        lines.extend(_wrap_segment(segment, line_length))
    return lines or [""]


def _wrap_segment(text: str, line_length: int) -> Iterable[str]:
    if not text:
        return [""]
    words = text.split()
    if not words:
        return [""]
    wrapped: list[str] = []
    current = words[0]
    for word in words[1:]:
        tentative = f"{current} {word}" if current else word
        if len(tentative) <= line_length:
            current = tentative
        else:
            if current:
                wrapped.append(current)
            if len(word) > line_length:
                wrapped.append(word)
                current = ""
            else:
                current = word
    if current:
        wrapped.append(current)
    return wrapped


__all__ = ["NewsBlock", "parse_news_blocks", "wrap_news_text"]
