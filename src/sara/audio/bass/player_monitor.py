"""BassPlayer monitor thread helper.

Kept as a separate module to keep `player_base.py` smaller and focused.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .player_base import BassPlayer


def start_monitor(
    player: "BassPlayer",
    *,
    monitor_interval: float,
    loop_guard_base_slack: float,
    loop_guard_fallback_slack: float,
    logger: logging.Logger,
) -> None:
    if player._monitor_thread and player._monitor_thread.is_alive():
        return
    player._monitor_stop.clear()

    def _runner() -> None:
        while not player._monitor_stop.is_set():
            try:
                if player._stream:
                    now = time.time()
                    if (
                        player._progress_callback
                        and player._current_item_id
                        and (now - player._last_progress_ts) >= 0.05
                    ):
                        try:
                            pos = player._manager.channel_get_seconds(player._stream)
                            player._progress_callback(player._current_item_id, pos)
                        except Exception:
                            pass
                        player._last_progress_ts = now
                    # nadzoruj pętlę również po stronie Python, żeby uniknąć pominiętych synców
                    if (
                        player._loop_guard_enabled
                        and player._loop_active
                        and player._loop_end is not None
                        and player._loop_start is not None
                    ):
                        try:
                            pos = player._manager.channel_get_seconds(player._stream)
                            now = time.time()
                            if player._debug_loop and (now - player._last_loop_debug_log) > 0.5:
                                logger.debug(
                                    "Loop debug: pos=%.6f start=%.6f end=%.6f stream=%s",
                                    pos,
                                    player._loop_start,
                                    player._loop_end,
                                    player._stream,
                                )
                                player._last_loop_debug_log = now
                            # strażnik awaryjny: pozwól syncowi zadziałać, a reaguj dopiero PO końcu
                            if (now - player._last_loop_jump_ts) > 0.004:
                                guard_slack = (
                                    loop_guard_base_slack
                                    if player._loop_guard_armed
                                    else loop_guard_fallback_slack
                                )
                                if pos > (player._loop_end + guard_slack):
                                    player._jump_to_loop_start("guard", pos)
                                    continue
                                # twardy clamp tylko przy dużym odjechaniu
                                if pos > (player._loop_end + 0.05):
                                    player._jump_to_loop_start("clamp", pos)
                                    continue
                        except Exception as exc:
                            if player._debug_loop:
                                logger.debug("Loop debug: guard check failed: %s", exc)
                    active = player._is_active()
                    if not active:
                        # Jeśli pętla ma być aktywna, próbujemy wznowić bez wyzwalania zakończenia
                        if player._loop_active and player._stream:
                            try:
                                if player._loop_start_bytes:
                                    player._manager.channel_set_position_bytes(
                                        player._stream, player._loop_start_bytes
                                    )
                                # jeśli strumień nie gra, wznów go
                                try:
                                    player._manager.channel_play(player._stream, False)
                                except Exception:
                                    pass
                            except Exception as exc:
                                if player._debug_loop:
                                    logger.debug("Loop debug: monitor restart failed: %s", exc)
                            # nawet jeśli się nie udało, nie zgłaszaj zakończenia – próbuj ponownie
                            time.sleep(monitor_interval)
                            continue
                        if player._finished_callback and player._current_item_id:
                            try:
                                player._finished_callback(player._current_item_id)
                            except Exception:
                                pass
                        # zwolnij zasoby po naturalnym zakończeniu
                        try:
                            player.stop(_from_fade=True)
                        except Exception:
                            pass
                        break
                time.sleep(monitor_interval)
            except Exception:
                break

    player._monitor_thread = threading.Thread(target=_runner, daemon=True, name="bass-monitor")
    player._monitor_thread.start()

