"""Callback entrypoints for mix/automix runtime."""

from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


def auto_mix_now_from_callback(frame, playlist_id: str, item_id: str) -> None:
    playlist = frame._get_playlist_model(playlist_id)
    if not playlist:
        return
    panel = frame._playlists.get(playlist_id)
    if not panel:
        return
    item = playlist.get_item(item_id)
    if not item:
        return
    try:
        frame._auto_mix_now(playlist, item, panel)
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("UI: auto_mix_now callback failed playlist=%s item=%s err=%s", playlist_id, item_id, exc)

