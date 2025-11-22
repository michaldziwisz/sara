"""Entry point for the SARA application."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import wx

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from sara.core.config import SettingsManager
from sara.core.i18n import set_language
from sara.ui.main_frame import MainFrame
from sara.ui.nvda_sleep import ensure_nvda_sleep_mode


_FAULTHANDLER_FILE = None


def _configure_logging() -> Optional[Path]:
    level_name = os.environ.get("LOGLEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)

    primary_dir = Path.cwd() / "logs"
    fallback_dir = Path(tempfile.gettempdir()) / "sara_logs"
    logs_dir = primary_dir
    log_path: Path | None = None

    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except Exception:  # pylint: disable=broad-except
        logs_dir = fallback_dir
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            logging.basicConfig(level=level)
            return None

    try:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_path = logs_dir / f"sara-{timestamp}.log"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logging.basicConfig(level=level, handlers=[file_handler, stream_handler])
    except Exception:  # pylint: disable=broad-except
        logging.basicConfig(level=level)
    if log_path:
        logging.getLogger(__name__).info("Writing log to %s", log_path)
        if logs_dir is fallback_dir:
            logging.getLogger(__name__).warning("Using fallback log directory %s", logs_dir)
    return log_path


def _enable_debug_dump(log_path: Optional[Path]) -> None:
    """Enable periodic stack dumps when running in debug mode."""
    if not (os.environ.get("SARA_DEBUG_STACK") or os.environ.get("LOGLEVEL", "").lower() == "debug"):
        return
    try:
        import faulthandler
    except Exception:  # pragma: no cover - faulthandler should always be present
        return

    global _FAULTHANDLER_FILE
    try:
        target = log_path.open("a", encoding="utf-8") if log_path else sys.stderr
        faulthandler.enable(file=target, all_threads=True)
        # Dump co 40s żeby nie zalewać logu (w wątpliwych przypadkach można ustawić SARA_DEBUG_STACK_INTERVAL)
        interval = float(os.environ.get("SARA_DEBUG_STACK_INTERVAL", "40"))
        if interval > 0:
            faulthandler.dump_traceback_later(interval, file=target, repeat=True)
        _FAULTHANDLER_FILE = target
        logging.getLogger(__name__).debug("Faulthandler stack dump enabled")
    except Exception:  # pylint: disable=broad-except
        pass


def run() -> None:
    """Start the main wxPython event loop."""
    log_path = _configure_logging()
    _enable_debug_dump(log_path)
    app = wx.App()
    settings = SettingsManager()
    set_language(settings.get_language())
    ensure_nvda_sleep_mode()
    frame = MainFrame(settings=settings)
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    run()
