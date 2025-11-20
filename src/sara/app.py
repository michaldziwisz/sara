"""Entry point for the SARA application."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

import wx

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from sara.core.config import SettingsManager
from sara.core.i18n import set_language
from sara.ui.main_frame import MainFrame
from sara.ui.nvda_sleep import ensure_nvda_sleep_mode


def _configure_logging() -> None:
    logs_dir = Path.cwd() / "logs"
    log_path: Path | None = None
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_path = logs_dir / f"sara-{timestamp}.log"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])
    except Exception:  # pylint: disable=broad-except
        # If logging setup fails (e.g., no write permission), fall back silently.
        logging.basicConfig(level=logging.INFO)
    if log_path:
        logging.getLogger(__name__).info("Writing log to %s", log_path)


def run() -> None:
    """Start the main wxPython event loop."""
    _configure_logging()
    app = wx.App()
    settings = SettingsManager()
    set_language(settings.get_language())
    ensure_nvda_sleep_mode()
    frame = MainFrame(settings=settings)
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    run()
