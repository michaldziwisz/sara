"""Simple gettext-based internationalization helper."""

from __future__ import annotations

import gettext as _gettext
import sys
from pathlib import Path


_DOMAIN = "sara"


def _default_locale_dir() -> Path:
    """Return directory containing locale files, handling frozen builds."""

    package_dir = Path(__file__).resolve().parent.parent / "locale"
    if getattr(sys, "frozen", False):  # pragma: no cover - only in packaged app
        candidates = []
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "locale")
        meipass = Path(getattr(sys, "_MEIPASS", exe_dir))
        candidates.append(meipass / "sara" / "locale")
        candidates.append(meipass / "locale")
        for candidate in candidates:
            if candidate.exists():
                return candidate
    return package_dir


class _I18n:
    def __init__(self) -> None:
        self._translation = _gettext.NullTranslations()

    def set_language(self, language: str | None) -> None:
        languages = None
        if language:
            languages = [language]
        self._translation = _gettext.translation(
            _DOMAIN,
            localedir=_default_locale_dir(),
            languages=languages,
            fallback=True,
        )

    def gettext(self, message: str) -> str:
        return self._translation.gettext(message)


_I18N = _I18n()


def set_language(language: str | None) -> None:
    """Configure active UI language."""

    _I18N.set_language(language)


def gettext(message: str) -> str:
    """Return translated message for current language."""

    return _I18N.gettext(message)


__all__ = ["set_language", "gettext"]
