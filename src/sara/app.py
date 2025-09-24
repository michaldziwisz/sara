"""Entry point for the SARA application."""

from __future__ import annotations

import sys
from pathlib import Path

import wx

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from sara.ui.main_frame import MainFrame
from sara.core.config import SettingsManager
from sara.core.i18n import set_language


def run() -> None:
    """Start the main wxPython event loop."""
    app = wx.App()
    settings = SettingsManager()
    set_language(settings.get_language())
    frame = MainFrame(settings=settings)
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    run()
