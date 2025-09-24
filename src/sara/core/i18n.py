"""Simple gettext-based internationalization helper."""

from __future__ import annotations

import gettext as _gettext
from pathlib import Path


_LOCALE_DIR = Path(__file__).resolve().parent.parent / "locale"
_DOMAIN = "sara"


class _I18n:
    def __init__(self) -> None:
        self._translation = _gettext.NullTranslations()

    def set_language(self, language: str | None) -> None:
        languages = None
        if language:
            languages = [language]
        self._translation = _gettext.translation(
            _DOMAIN,
            localedir=_LOCALE_DIR,
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
