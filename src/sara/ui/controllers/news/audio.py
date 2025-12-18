"""News panel audio helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistModel


def news_device_entries(
    frame,
    *,
    placeholder_label: str | None = None,
) -> list[tuple[str | None, str]]:
    if placeholder_label is None:
        placeholder_label = _("(use global/PFL device)")
    entries: list[tuple[str | None, str]] = [(None, placeholder_label)]
    entries.extend((device.id, device.name) for device in frame._audio_engine.get_devices())
    return entries


def play_news_audio_clip(frame, model: PlaylistModel, clip_path: Path, device_id: str | None) -> None:
    if not clip_path.exists():
        frame._announce_event("device", _("Audio file %s does not exist") % clip_path)
        return
    configured = model.get_configured_slots()
    target_device = device_id or (configured[0] if configured else None) or frame._settings.get_pfl_device()
    if not target_device:
        frame._announce_event("device", _("Select a playback device first"))
        return
    try:
        player = frame._audio_engine.create_player(target_device)
    except ValueError:
        frame._announce_event("device", _("Device %s is not available") % target_device)
        return
    try:
        player.play(f"{model.id}:news", str(clip_path))
    except Exception as exc:  # pylint: disable=broad-except
        frame._announce_event("device", _("Failed to play audio clip: %s") % exc)


def preview_news_clip(
    frame,
    clip_path: Path,
    *,
    start_preview: Callable[[PlaylistItem, float], bool] | None = None,
    on_missing: Callable[[Path], None] | None = None,
    item_id_prefix: str = "news-preview",
) -> bool:
    if not clip_path.exists():
        if on_missing is not None:
            on_missing(clip_path)
        else:
            frame._announce_event("pfl", _("Audio file %s does not exist") % clip_path)
        return False
    temp_item = PlaylistItem(
        id=f"{item_id_prefix}-{clip_path.stem}",
        path=clip_path,
        title=clip_path.name,
        duration_seconds=0.0,
    )
    if start_preview is None:
        start_preview = frame._playback.start_preview
    return start_preview(temp_item, 0.0)
