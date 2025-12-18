"""Application configuration management package.

The public API remains available as `sara.core.config` while implementation is
split into focused modules.
"""

from __future__ import annotations

from .defaults import DEFAULT_ANNOUNCEMENTS, DEFAULT_CONFIG
from .settings import SettingsManager

__all__ = [
    "DEFAULT_ANNOUNCEMENTS",
    "DEFAULT_CONFIG",
    "SettingsManager",
]
