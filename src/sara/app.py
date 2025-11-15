"""Entry point for the SARA application."""

from __future__ import annotations

import sys
from pathlib import Path

import wx

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from sara.core.config import SettingsManager
from sara.core.i18n import set_language
from sara.ui.main_frame import MainFrame
from sara.ui.nvda_sleep import ensure_nvda_sleep_mode


def run() -> None:
    """Start the main wxPython event loop."""
    app = wx.App()
    settings = SettingsManager()
    set_language(settings.get_language())
    ensure_nvda_sleep_mode()
    frame = MainFrame(settings=settings)
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    run()
