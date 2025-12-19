"""M3U playlist parsing/serialization helpers."""

from __future__ import annotations

from typing import Any, Iterable

from sara.core.playlist import PlaylistItem


def parse_m3u_lines(lines: Iterable[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current_title: str | None = None
    current_duration: float | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#EXTM3U"):
            continue
        if stripped.startswith("#EXTINF:"):
            try:
                header, title = stripped.split(",", 1)
            except ValueError:
                header, title = stripped, ""
            try:
                duration = float(header[8:])
            except ValueError:
                duration = None
            current_duration = duration if duration and duration >= 0 else None
            current_title = title.strip() if title.strip() else None
            continue

        entry_path = stripped
        entries.append(
            {
                "path": entry_path,
                "title": current_title,
                "duration": current_duration,
            }
        )
        current_title = None
        current_duration = None

    return entries


def serialize_m3u(items: Iterable[PlaylistItem]) -> str:
    lines = ["#EXTM3U"]
    for item in items:
        duration = int(item.duration_seconds) if item.duration_seconds else -1
        lines.append(f"#EXTINF:{duration},{item.title}")
        lines.append(str(item.path.resolve()))
    return "\n".join(lines) + "\n"

