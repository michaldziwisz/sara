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


def loop_guard_reason(
    *,
    native_active: bool,
    pos: float,
    loop_end: float,
    guard_slack: float,
    clamp_slack: float = 0.05,
) -> str | None:
    """Zdecyduj, czy pythonowy strażnik pętli ma wymusić skok na początek.

    Strażnik jest WYŁĄCZNIE siatką awaryjną dla trybu marker-sync (gdy natywna
    pętla BASS jest niedostępna). Gdy pętla natywna jest aktywna, BASS zawija
    materiał próbka-w-próbkę w mixtime i pythonowy skok tylko by dublował tę
    pracę (ryzyko podwójnego skoku/kliknięcia/dryfu) — wtedy zwracamy None.

    Zwraca: "guard", "clamp" albo None.
    """
    if native_active:
        return None
    if pos > (loop_end + clamp_slack):
        return "clamp"
    if pos > (loop_end + guard_slack):
        return "guard"
    return None


def python_guard_active(player: "BassPlayer") -> bool:
    """Czy pythonowy strażnik pętli realnie odpowiada za zawijanie materiału.

    Strażnik (a wraz z nim ciasny takt monitora) jest potrzebny TYLKO w trybie
    marker-sync — gdy natywna pętla BASS jest niedostępna. Gdy pętla nie jest
    aktywna albo zawija ją natywnie BASS, monitor nie musi odpytywać pozycji co
    1 ms; wystarczy mu rozluźniony takt na postęp (i tak dławiony do 50 ms) oraz
    wykrycie końca strumienia. Rozluźnienie taktu w tych przypadkach znacząco
    zmniejsza presję na scheduler OS, a tym samym jitter dyspozycji natywnego
    callbacku miksu (objaw: punkt miksu na PFL „pływa" po dłuższej sesji).
    """
    return bool(
        player._loop_guard_enabled
        and player._loop_active
        and player._loop_start is not None
        and player._loop_end is not None
        and not player._loop_native_active
    )


def start_monitor(
    player: "BassPlayer",
    *,
    monitor_interval: float,
    loop_guard_base_slack: float,
    loop_guard_fallback_slack: float,
    logger: logging.Logger,
    monitor_idle_interval: float | None = None,
) -> None:
    if player._monitor_thread and player._monitor_thread.is_alive():
        return
    player._monitor_stop.clear()
    # Takt rozluźniony, gdy pythonowy strażnik pętli nie jest potrzebny.
    idle_interval = monitor_interval if monitor_idle_interval is None else max(monitor_interval, monitor_idle_interval)

    def _runner() -> None:
        while not player._monitor_stop.is_set():
            # Dobierz takt tej iteracji: ciasny tylko, gdy odpowiada za to pętla.
            effective_interval = monitor_interval if python_guard_active(player) else idle_interval
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
                    loop_active = player._loop_active
                    loop_start = player._loop_start
                    loop_end = player._loop_end
                    if (
                        player._loop_guard_enabled
                        and loop_active
                        and loop_end is not None
                        and loop_start is not None
                    ):
                        try:
                            pos = player._manager.channel_get_seconds(player._stream)
                            now = time.time()
                            if player._debug_loop and (now - player._last_loop_debug_log) > 0.5:
                                logger.debug(
                                    "Loop debug: pos=%.6f start=%.6f end=%.6f stream=%s",
                                    pos,
                                    loop_start,
                                    loop_end,
                                    player._stream,
                                )
                                player._last_loop_debug_log = now
                            # strażnik awaryjny: pozwól syncowi zadziałać, a reaguj dopiero PO końcu.
                            # Aktywny tylko w trybie marker-sync; przy natywnej pętli BASS zawija sam.
                            if (now - player._last_loop_jump_ts) > 0.004:
                                guard_slack = (
                                    loop_guard_base_slack
                                    if player._loop_guard_armed
                                    else loop_guard_fallback_slack
                                )
                                reason = loop_guard_reason(
                                    native_active=player._loop_native_active,
                                    pos=pos,
                                    loop_end=loop_end,
                                    guard_slack=guard_slack,
                                )
                                if reason is not None:
                                    player._jump_to_loop_start(reason, pos)
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
                            time.sleep(effective_interval)
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
                time.sleep(effective_interval)
            except Exception:
                break

    player._monitor_thread = threading.Thread(target=_runner, daemon=True, name="bass-monitor")
    player._monitor_thread.start()
