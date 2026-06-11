"""PFL preview helpers extracted from `PlaybackController`.

The goal is to keep `sara.ui.playback_controller` smaller while preserving
behaviour via thin delegating methods.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from sara.audio.engine import Player
from sara.core.i18n import gettext as _
from sara.core.mix_planner import fade_duration_at_mix
from sara.core.playlist import PlaylistItem


logger = logging.getLogger(__name__)


def _format_player_position(player: Player) -> str:
    getter = getattr(player, "get_position_seconds", None)
    if not callable(getter):
        return "unknown"
    try:
        return f"{float(getter()):.3f}"
    except Exception:  # pylint: disable=broad-except
        return "unknown"


@dataclass
class PreviewContext:
    players: list[Player]
    device_id: str
    item_path: Path
    finished_event: Event | None = None


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
        if loop_range:
            player.set_loop(loop_range[0], loop_range[1])
        else:
            player.set_loop(None, None)
        finished_event = player.play(
            item.id + ":preview",
            str(item.path),
            start_seconds=start,
            # Pozwól na zapętlenie tylko przy aktywnym loop_range – w pozostałych
            # przypadkach podsłuch powinien naturalnie się zatrzymać.
            allow_loop=bool(loop_range),
        )
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
    current_base_cue: float | None = None,
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
    base_cue = (
        max(0.0, float(current_base_cue))
        if current_base_cue is not None
        else (current_item.cue_in_seconds or 0.0)
    )
    effective_duration = (
        max(0.0, current_effective_duration)
        if current_effective_duration is not None
        else max(0.0, (current_item.duration_seconds or 0.0) - base_cue)
    )
    fade_len = fade_duration_at_mix(fade_seconds, mix_at_seconds, base_cue, effective_duration)
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
    fired_event = Event()
    preview_started_at = time.perf_counter()

    # jeśli trigger w przeszłości, odpal B natychmiast i skróć pre-window
    if delay_b <= 0:
        delay_b = 0.0
        start_a = max(0.0, mix_at_seconds - pre_seconds)

    def _fire_mix(source: str = "native") -> None:
        if stop_event.is_set():
            logger.debug(
                "PFL mix preview: fire ignored source=%s reason=stopped mix_at=%.3f a_pos=%s",
                source,
                mix_at_seconds,
                _format_player_position(player_a),
            )
            return
        if fired_event.is_set():
            logger.debug(
                "PFL mix preview: fire ignored source=%s reason=already_fired mix_at=%.3f a_pos=%s",
                source,
                mix_at_seconds,
                _format_player_position(player_a),
            )
            return
        fired_event.set()
        elapsed = time.perf_counter() - preview_started_at
        pos_a = _format_player_position(player_a)
        logger.debug(
            "PFL mix preview: fire source=%s mix_at=%.3f start_a=%.3f delay=%.3f elapsed=%.3f "
            "a_pos=%s next_start=%.3f fade=%.3f native=%s",
            source,
            mix_at_seconds,
            start_a,
            delay_b,
            elapsed,
            pos_a,
            next_start,
            fade_len,
            supports_native_trigger,
        )
        try:
            player_b.play(next_item.id, str(next_item.path), start_seconds=next_start, allow_loop=False)
        except Exception:  # pylint: disable=broad-except
            logger.debug(
                "PFL mix preview: next start failed source=%s mix_at=%.3f a_pos=%s next_start=%.3f",
                source,
                mix_at_seconds,
                pos_a,
                next_start,
                exc_info=True,
            )
            return
        logger.debug(
            "PFL mix preview: next started source=%s mix_at=%.3f a_pos=%s b_pos=%s next_start=%.3f",
            source,
            mix_at_seconds,
            pos_a,
            _format_player_position(player_b),
            next_start,
        )
        if fade_len > 0:
            try:
                player_a.fade_out(fade_len)
                logger.debug(
                    "PFL mix preview: fade_out source=%s duration=%.3f mix_at=%.3f a_pos=%s",
                    source,
                    fade_len,
                    mix_at_seconds,
                    _format_player_position(player_a),
                )
            except Exception:  # pylint: disable=broad-except
                logger.debug(
                    "PFL mix preview: fade_out failed source=%s duration=%.3f mix_at=%.3f",
                    source,
                    fade_len,
                    mix_at_seconds,
                    exc_info=True,
                )
                pass

    supports_native_trigger = False
    support_checker = getattr(controller, "supports_mix_trigger", None)
    if callable(support_checker):
        try:
            supports_native_trigger = bool(support_checker(player_a))
        except Exception:
            supports_native_trigger = False
    else:
        support_attr = getattr(player_a, "supports_mix_trigger", None)
        try:
            supports_native_trigger = bool(support_attr()) if callable(support_attr) else bool(support_attr)
        except Exception:
            supports_native_trigger = False

    def _schedule_mix_timer(*, guard_seconds: float = 0.0) -> None:
        if delay_b <= 0:
            _fire_mix("immediate")
            return

        def _fallback_wait() -> None:
            stop_event.wait(timeout=max(0.0, delay_b + guard_seconds))
            if stop_event.is_set():
                return
            if fired_event.is_set():
                logger.debug(
                    "PFL mix preview: timer fallback skipped mix_at=%.3f delay=%.3f guard=%.3f "
                    "native=%s reason=already_fired a_pos=%s",
                    mix_at_seconds,
                    delay_b,
                    guard_seconds,
                    supports_native_trigger,
                    _format_player_position(player_a),
                )
                return
            logger.debug(
                "PFL mix preview: timer fallback firing mix_at=%.3f delay=%.3f guard=%.3f native=%s a_pos=%s",
                mix_at_seconds,
                delay_b,
                guard_seconds,
                supports_native_trigger,
                _format_player_position(player_a),
            )
            _fire_mix("timer")

        threading.Thread(target=_fallback_wait, daemon=True).start()

    try:
        play_kwargs = {"start_seconds": start_a, "allow_loop": False}
        if supports_native_trigger:
            play_kwargs["mix_trigger_seconds"] = mix_at_seconds
            play_kwargs["on_mix_trigger"] = lambda: _fire_mix("native")
        logger.debug(
            "PFL mix preview: arming trigger native=%s mix_at=%.3f start_a=%.3f delay=%.3f "
            "fade=%.3f next_start=%.3f device=%s",
            supports_native_trigger,
            mix_at_seconds,
            start_a,
            delay_b,
            fade_len,
            next_start,
            pfl_device_id,
        )
        player_a.play(current_item.id, str(current_item.path), **play_kwargs)
    except Exception as exc:  # pylint: disable=broad-except
        controller._announce("pfl", _("Failed to start mix preview: %s") % exc)
        return False

    if supports_native_trigger:
        _schedule_mix_timer(guard_seconds=0.05)
    else:
        _schedule_mix_timer()

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
    )
    return True


def update_loop_preview(controller, item: PlaylistItem, start: float, end: float) -> bool:
    if end <= start:
        return False
    context = controller._preview_context
    if not context or context.item_path != item.path:
        return False
    players = getattr(context, "players", None) or []
    if not players:
        return False
    try:
        players[0].set_loop(start, end)
    except Exception as exc:  # pylint: disable=broad-except
        controller._announce("pfl", _("Preview error: %s") % exc)
        return False
    return True
