from __future__ import annotations

from typing import Any, Callable


def _direct_call(callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return callback(*args, **kwargs)

