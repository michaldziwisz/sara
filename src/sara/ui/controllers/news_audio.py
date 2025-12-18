"""Compatibility wrapper for news audio helpers.

Implementation lives in `sara.ui.controllers.news.audio`.
"""

from __future__ import annotations

from sara.ui.controllers.news.audio import news_device_entries, play_news_audio_clip, preview_news_clip

__all__ = [
    "news_device_entries",
    "play_news_audio_clip",
    "preview_news_clip",
]

