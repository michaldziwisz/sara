"""Clipboard + playlist item serialization helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import wx

from sara.core.playlist import PlaylistItem


def serialize_items(items: list[PlaylistItem]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for item in items:
        serialized.append(
            {
                "path": str(item.path),
                "title": item.title,
                "artist": item.artist,
                "duration": item.duration_seconds,
                "replay_gain_db": item.replay_gain_db,
                "cue_in": item.cue_in_seconds,
                "segue": item.segue_seconds,
                "segue_fade": item.segue_fade_seconds,
                "overlap": item.overlap_seconds,
                "intro": item.intro_seconds,
                "outro": item.outro_seconds,
                "loop_start": item.loop_start_seconds,
                "loop_end": item.loop_end_seconds,
                "loop_auto_enabled": item.loop_auto_enabled,
                "loop_enabled": item.loop_enabled,
            }
        )
    return serialized


def create_item_from_serialized(frame, data: dict[str, Any]) -> PlaylistItem:
    path = Path(data["path"])
    loop_auto_enabled = bool(data.get("loop_auto_enabled"))
    loop_enabled = bool(data.get("loop_enabled")) or loop_auto_enabled
    item = frame._playlist_factory.create_item(
        path=path,
        title=data.get("title", path.stem),
        artist=data.get("artist"),
        duration_seconds=float(data.get("duration", 0.0)),
        replay_gain_db=data.get("replay_gain_db"),
        cue_in_seconds=data.get("cue_in"),
        segue_seconds=data.get("segue"),
        segue_fade_seconds=data.get("segue_fade"),
        overlap_seconds=data.get("overlap"),
        intro_seconds=data.get("intro"),
        outro_seconds=data.get("outro"),
        loop_start_seconds=data.get("loop_start"),
        loop_end_seconds=data.get("loop_end"),
        loop_auto_enabled=loop_auto_enabled,
        loop_enabled=loop_enabled,
    )
    return item


def get_system_clipboard_paths() -> list[Path]:
    paths: list[Path] = []
    clipboard = wx.TheClipboard
    if not clipboard.Open():
        return paths
    try:
        data = wx.FileDataObject()
        if clipboard.GetData(data):
            paths = [Path(filename) for filename in data.GetFilenames()]
    finally:
        clipboard.Close()
    return paths


def set_system_clipboard_paths(paths: list[Path]) -> None:
    clipboard = wx.TheClipboard
    if not clipboard.Open():
        return
    try:
        data = wx.FileDataObject()
        added = False
        for path in paths:
            try:
                data.AddFile(str(path))
                added = True
            except Exception:
                continue
        if added:
            clipboard.SetData(data)
    finally:
        clipboard.Close()

