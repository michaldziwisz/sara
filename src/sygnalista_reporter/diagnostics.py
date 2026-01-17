from __future__ import annotations

import locale
import platform
import sys
import time
from typing import Any


def collect_diagnostics(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "python": {
            "python_version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "locale": {
            "locale": locale.getlocale(),
            "preferred_encoding": locale.getpreferredencoding(False),
            "tzname": time.tzname,
        },
    }

    if extra:
        diagnostics["extra"] = extra

    return diagnostics

