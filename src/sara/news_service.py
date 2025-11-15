"""Serialization helpers for text-based news services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class NewsService:
    """Portable representation of a news playlist."""

    title: str
    markdown: str
    output_device: str | None = None
    line_length: int | None = None


def load_news_service(path: Path) -> NewsService:
    """Load a news service from JSON (with plain-text fallback)."""

    text = path.read_text(encoding="utf-8")
    try:
        payload: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError:
        return NewsService(title=path.stem, markdown=text)

    markdown = str(payload.get("markdown") or payload.get("text") or "")
    title = str(payload.get("title") or path.stem)
    output_device = payload.get("output_device")
    if output_device is not None:
        output_device = str(output_device)
    line_length = payload.get("line_length")
    try:
        line_length_value: int | None
        if line_length is None:
            line_length_value = None
        else:
            line_length_value = max(0, int(line_length))
    except (TypeError, ValueError):
        line_length_value = None
    return NewsService(
        title=title,
        markdown=markdown,
        output_device=output_device,
        line_length=line_length_value,
    )


def save_news_service(path: Path, service: NewsService) -> None:
    """Persist a news service to JSON."""

    payload = {
        "version": 1,
        "title": service.title,
        "markdown": service.markdown,
        "output_device": service.output_device,
        "line_length": service.line_length,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
