"""Compatibility wrapper for News edit/read controllers.

Implementation lives in `sara.ui.controllers.news.mode`.
"""

from __future__ import annotations

from sara.ui.controllers.news.mode import NewsEditController, NewsReadController, ReadKeyAction

__all__ = [
    "NewsEditController",
    "NewsReadController",
    "ReadKeyAction",
]
