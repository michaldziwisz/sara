"""Best-effort filesystem warm-up helpers.

These helpers are used to reduce start latency when audio files live on slow
storage (HDD/NAS/network). They do not decode audio; they just read file data
so the OS can keep it in the page cache.
"""

from __future__ import annotations

import logging
from pathlib import Path


logger = logging.getLogger(__name__)


def warm_file(path: Path, *, max_bytes: int, chunk_bytes: int = 1024 * 1024) -> int:
    """Read up to `max_bytes` from `path` to warm the OS file cache.

    Returns number of bytes read. Errors are swallowed and logged at debug level.
    """
    max_bytes = int(max_bytes)
    if max_bytes <= 0:
        return 0
    chunk_bytes = max(1, int(chunk_bytes))
    path = Path(path)
    if not path.exists() or not path.is_file():
        return 0

    read_total = 0
    try:
        with path.open("rb") as handle:
            remaining = max_bytes
            while remaining > 0:
                data = handle.read(min(chunk_bytes, remaining))
                if not data:
                    break
                read_total += len(data)
                remaining -= len(data)
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("File warm-up failed for %s: %s", path, exc)
        return 0
    return read_total

