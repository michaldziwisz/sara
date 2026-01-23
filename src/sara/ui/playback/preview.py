"""PFL preview helpers extracted from `PlaybackController`.

The goal is to keep `sara.ui.playback_controller` smaller while preserving
behaviour via thin delegating methods.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from sara.audio.engine import Player
from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem


logger = logging.getLogger(__name__)


@dataclass
class PreviewContext:
    players: list[Player]
    device_id: str
    item_path: Path
    finished_event: Event | None = None
    mix_executor: object | None = None


def stop_preview(controller, *, wait: bool = True) -> None:
    if not controller._preview_context:
        return
    context = controller._preview_context
    controller._preview_context = None
    finished_event = context.finished_event if wait else None
    # sygnalizuj wątkom podglądu, że mają się zatrzymać
    try:
        if context.finished_event:
            context.finished_event.set()
    except Exception:  # pylint: disable=broad-except
        pass
    for player in context.players:
        try:
            if hasattr(player, "set_loop"):
                player.set_loop(None, None)
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            player.stop()
        except Exception:  # pylint: disable=broad-except
            pass
    if wait and finished_event:
        try:
            finished_event.wait(timeout=0.5)
        except Exception:  # pylint: disable=broad-except
            pass
    try:
        executor = getattr(context, "mix_executor", None)
        shutdown = getattr(executor, "shutdown", None) if executor else None
        if callable(shutdown):
            shutdown()
    except Exception:  # pragma: no cover - best-effort cleanup
        pass


def _resolve_mix_executor(controller) -> str:
    env_value = os.environ.get("SARA_MIX_EXECUTOR")
    if env_value:
        return env_value.strip().lower()
    settings = getattr(controller, "_settings", None)
    getter = getattr(settings, "get_playback_mix_executor", None)
    if callable(getter):
        try:
            return str(getter()).strip().lower()
        except Exception:
            pass
    return "ui"


def _can_load_rust_executor() -> bool:
    # Avoid trying to load the DLL in environments where it won't exist.
    return sys.platform.startswith("win") or sys.platform == "darwin" or sys.platform.startswith("linux")


def start_preview(
    controller,
    item: PlaylistItem,
    start: float,
    *,
    loop_range: tuple[float, float] | None = None,
) -> bool:
    logger.debug(
        "PlaybackController: start_preview item=%s start=%.3f loop=%s device=%s",
        getattr(item, "title", item.id),
        start,
        loop_range,
        controller._pfl_device_id,
    )
    if loop_range is not None and loop_range[1] <= loop_range[0]:
        controller._announce("loop", _("Loop end must be greater than start"))
        return False

    stop_preview(controller, wait=True)

    pfl_device_id = controller._pfl_device_id or controller._settings.get_pfl_device()
    if not pfl_device_id:
        controller._announce("pfl", _("Configure a PFL device in Options"))
        return False

    known_devices = {device.id for device in controller._audio_engine.get_devices()}
    if pfl_device_id not in known_devices:
        controller._audio_engine.refresh_devices()
        known_devices = {device.id for device in controller._audio_engine.get_devices()}
    if pfl_device_id not in known_devices:
        controller._announce("pfl", _("Selected PFL device is not available"))
        return False

    if pfl_device_id in controller.get_busy_device_ids():
        controller._announce("pfl", _("PFL device is currently in use"))
        return False

    try:
        player = controller._audio_engine.create_player_instance(pfl_device_id)
    except Exception as exc:  # pylint: disable=broad-except
        controller._announce("pfl", _("Failed to prepare PFL preview: %s") % exc)
        return False

    finished_event: Event | None = None
    fallback_finished = Event()

    def _on_finished(_item_id: str) -> None:
        try:
            fallback_finished.set()
        except Exception:  # pylint: disable=broad-except
            pass
        context = controller._preview_context
        if not context:
            return
        if context.item_path != item.path:
            return
        if context.device_id != pfl_device_id:
            return
        players = getattr(context, "players", None) or []
        if player not in players:
            return
        controller._preview_context = None

    try:
        player.set_finished_callback(_on_finished)
        player.set_progress_callback(None)
        player.set_gain_db(item.replay_gain_db)
        finished_event = player.play(
            item.id + ":preview",
            str(item.path),
            start_seconds=start,
            # Pozwól na zapętlenie tylko przy aktywnym loop_range – w pozostałych
            # przypadkach podsłuch powinien naturalnie się zatrzymać.
            allow_loop=bool(loop_range),
        )
        if loop_range:
            player.set_loop(loop_range[0], loop_range[1])
        else:
            player.set_loop(None, None)
    except Exception as exc:  # pylint: disable=broad-except
        controller._announce("pfl", _("Preview error: %s") % exc)
        try:
            player.stop()
        except Exception:  # pylint: disable=broad-except
            pass
        return False

    if finished_event is None:
        finished_event = fallback_finished

    controller._preview_context = PreviewContext(
        players=[player],
        device_id=pfl_device_id,
        item_path=item.path,
        finished_event=finished_event,
    )
    return True


def start_mix_preview(
    controller,
    current_item: PlaylistItem,
    next_item: PlaylistItem,
    *,
    mix_at_seconds: float,
    pre_seconds: float = 4.0,
    fade_seconds: float = 0.0,
    current_effective_duration: float | None = None,
    next_cue_override: float | None = None,
) -> bool:
    """Preview crossfade/mix between current and next track on the PFL device.

    Używa dwóch playerów na tym samym urządzeniu PFL. Player A startuje kilka sekund
    przed punktem miksu, player B startuje dokładnie w punkcie mix_at_seconds (relatywnie
    do startu A). Fade A jest stosowany opcjonalnie.
    """
    stop_preview(controller, wait=False)

    pfl_device_id = controller._pfl_device_id or controller._settings.get_pfl_device()
    if not pfl_device_id:
        controller._announce("pfl", _("Configure a PFL device in Options"))
        return False

    known_devices = {device.id for device in controller._audio_engine.get_devices()}
    if pfl_device_id not in known_devices:
        controller._audio_engine.refresh_devices()
        known_devices = {device.id for device in controller._audio_engine.get_devices()}
    if pfl_device_id not in known_devices:
        controller._announce("pfl", _("Selected PFL device is not available"))
        return False

    try:
        player_a = controller._audio_engine.create_player_instance(pfl_device_id)
        player_b = controller._audio_engine.create_player_instance(pfl_device_id)
    except Exception as exc:  # pylint: disable=broad-except
        controller._announce("pfl", _("Failed to prepare mix preview: %s") % exc)
        return False

    try:
        player_a.set_gain_db(current_item.replay_gain_db)
    except Exception:  # pylint: disable=broad-except
        pass
    try:
        player_b.set_gain_db(next_item.replay_gain_db)
    except Exception:  # pylint: disable=broad-except
        pass

    start_a = max(0.0, mix_at_seconds - pre_seconds)
    effective_duration = (
        max(0.0, current_effective_duration)
        if current_effective_duration is not None
        else current_item.effective_duration_seconds
    )
    remaining_current = max(0.0, effective_duration - mix_at_seconds)
    fade_len = min(max(0.0, fade_seconds), remaining_current) if remaining_current > 0 else 0.0
    next_start = next_cue_override if next_cue_override is not None else (next_item.cue_in_seconds or 0.0)
    delay_b = max(0.0, mix_at_seconds - start_a)

    logger.debug(
        "PFL mix preview: current=%s next=%s mix_at=%.3f pre=%.3f fade=%.3f cue_next=%.3f",
        current_item.title,
        next_item.title,
        mix_at_seconds,
        pre_seconds,
        fade_len,
        next_start,
    )

    preload_enabled = getattr(controller, "_preload_enabled", True)
    if preload_enabled and next_item.path.exists():
        preloader = getattr(player_b, "preload", None)
        if callable(preloader):
            try:
                preloader(str(next_item.path), start_seconds=next_start, allow_loop=False)
            except Exception:  # pragma: no cover - best-effort
                logger.debug("PFL mix preview: preload failed", exc_info=True)
        else:
            warmer = getattr(controller, "_schedule_file_warmup", None)
            if callable(warmer):
                try:
                    warmer(next_item.path)
                except Exception:  # pragma: no cover - best-effort
                    logger.debug("PFL mix preview: warm-up failed", exc_info=True)

    stop_event = Event()
    callback_executor = None
    mix_executor = _resolve_mix_executor(controller)
    if mix_executor == "rust" and _can_load_rust_executor():
        try:
            from sara.ui.mix_runtime.rust_executor import RustCallbackExecutor

            callback_executor = RustCallbackExecutor()
        except Exception:
            callback_executor = None

    # jeśli trigger w przeszłości, odpal B natychmiast i skróć pre-window
    if delay_b <= 0:
        delay_b = 0.0
        start_a = max(0.0, mix_at_seconds - pre_seconds)

    def _fire_mix() -> None:
        if stop_event.is_set():
            return
        try:
            player_b.play(next_item.id, str(next_item.path), start_seconds=next_start, allow_loop=False)
        except Exception:
            return
        if fade_len > 0:
            try:
                player_a.fade_out(fade_len)
            except Exception:
                pass

    def _schedule_mix_trigger() -> None:
        if delay_b <= 0:
            _fire_mix()
            return

        def _on_native_trigger() -> None:
            if callback_executor:
                try:
                    callback_executor.submit(_fire_mix)
                except Exception:
                    _fire_mix()
                return
            _fire_mix()

        apply_trigger = getattr(player_a, "_apply_mix_trigger", None)
        if callable(apply_trigger):
            try:
                apply_trigger(mix_at_seconds, _on_native_trigger)
                return
            except Exception:  # pragma: no cover - defensywne
                logger.debug("PFL mix preview: failed to arm BASS trigger, falling back to timer", exc_info=True)

        def _fallback_wait() -> None:
            stop_event.wait(timeout=delay_b)
            if stop_event.is_set():
                return
            _fire_mix()

        threading.Thread(target=_fallback_wait, daemon=True).start()

    try:
        player_a.play(current_item.id, str(current_item.path), start_seconds=start_a, allow_loop=False)
    except Exception as exc:  # pylint: disable=broad-except
        controller._announce("pfl", _("Failed to start mix preview: %s") % exc)
        return False

    _schedule_mix_trigger()

    # auto-stop po krótkim oknie odsłuchu (pre + fade + zapas)
    total_preview = pre_seconds + max(fade_len, 0.0) + 4.0

    def _auto_stop() -> None:
        stop_event.wait(timeout=total_preview)
        stop_preview(controller, wait=False)

    threading.Thread(target=_auto_stop, daemon=True).start()

    controller._preview_context = PreviewContext(
        players=[player_a, player_b],
        device_id=pfl_device_id,
        item_path=current_item.path,
        finished_event=stop_event,
        mix_executor=callback_executor,
    )
    return True


def update_loop_preview(controller, item: PlaylistItem, start: float, end: float) -> bool:
    if end <= start:
        return False
    context = controller._preview_context
    if not context or context.item_path != item.path:
        return False
    try:
        context.player.set_loop(start, end)
    except Exception as exc:  # pylint: disable=broad-except
        controller._announce("pfl", _("Preview error: %s") % exc)
        return False
    return True
