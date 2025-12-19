"""Mixer thread loop helper.

This module keeps the mixing thread orchestration separate from the core
`DeviceMixer` class, making it easier to test and reason about.
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional, Protocol, Tuple


class _HasWrite(Protocol):
    def write(self, data) -> None: ...


class _StreamFactory(Protocol):
    def __call__(self, samplerate: float, channels: int): ...


def run_mixer_loop(
    *,
    stream_factory: _StreamFactory,
    samplerate: float,
    channels: int,
    stop_event,
    active_event,
    mix_once: Callable[[], Tuple[object, list[tuple[str, float, Callable[[str, float], None]]], list[str]]],
    finalize_source: Callable[[str], None],
    logger=None,
) -> None:
    """Run the mixer loop until `stop_event` is set.

    The function is intentionally dependency-light: it receives all required
    callables and events from the owning `DeviceMixer` instance.
    """

    if logger is None:  # pragma: no cover - defensive fallback
        import logging

        logger = logging.getLogger(__name__)

    try:
        with stream_factory(float(samplerate), int(channels)) as stream:  # type: ignore[assignment]
            stream = stream  # keep a local name for clarity
            while not stop_event.is_set():
                if not active_event.wait(timeout=0.05):
                    continue
                block, progresses, finished_ids = mix_once()
                if block is None:
                    active_event.clear()
                    continue
                try:
                    stream.write(block)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Błąd zapisu do strumienia mixer: %s", exc)
                    break
                for source_id, seconds, callback in progresses:
                    try:
                        callback(source_id, seconds)
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.error("Błąd callbacku postępu mixer: %s", exc)
                for source_id in finished_ids:
                    finalize_source(source_id)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Błąd wątku DeviceMixer: %s", exc)
    finally:
        active_event.clear()

