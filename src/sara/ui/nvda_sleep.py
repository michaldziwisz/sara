"""Compatibility wrapper for NVDA sleep helpers.

Implementation lives in `sara.ui.services.nvda_sleep`.
"""

from __future__ import annotations

from sara.ui.services.nvda_sleep import SaraSleepRegistry, ensure_nvda_sleep_mode, notify_nvda_play_next

__all__ = [
    "SaraSleepRegistry",
    "ensure_nvda_sleep_mode",
    "notify_nvda_play_next",
]
