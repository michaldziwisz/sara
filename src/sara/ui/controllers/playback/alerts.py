"""Intro/track-end alert helpers."""

from __future__ import annotations

from importlib.resources import files
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import wx

from sara.audio.engine import Player
from sara.core.i18n import gettext as _
from sara.core.mix_planner import compute_air_duration_seconds
from sara.core.playlist import PlaylistItem
from sara.ui.playback_controller import PlaybackContext

if TYPE_CHECKING:  # pragma: no cover
    from sara.ui.playlist_panel import PlaylistPanel


logger = logging.getLogger(__name__)


def _is_preview_active(frame) -> bool:
    """Return True when PFL preview is currently active (players still playing)."""
    context = getattr(frame, "_playback", None)
    context = getattr(context, "preview_context", None)
    if not context:
        return False
    players = getattr(context, "players", None) or []
    for player in players:
        is_active = getattr(player, "is_active", None)
        try:
            if callable(is_active) and is_active():
                return True
        except Exception:  # pylint: disable=broad-except
            continue
    return False


def compute_intro_remaining(item: PlaylistItem, absolute_seconds: float | None = None) -> float | None:
    intro = item.intro_seconds
    if intro is None:
        return None
    if absolute_seconds is None:
        absolute = (item.cue_in_seconds or 0.0) + item.current_position
    else:
        absolute = absolute_seconds
    remaining = intro - absolute
    if remaining <= 0:
        return 0.0
    return remaining


def announce_intro_remaining(frame, remaining: float, *, prefix_only: bool = False) -> None:
    seconds = max(0.0, remaining)
    if prefix_only:
        message = f"{seconds:.0f} seconds"
    else:
        message = _("Intro remaining: {seconds:.0f} seconds").format(seconds=seconds)
    frame._announce_event("intro_alert", message)


def announce_track_end_remaining(frame, remaining: float) -> None:
    seconds = max(0.0, remaining)
    message = _("Track ending in {seconds:.0f} seconds").format(seconds=seconds)
    frame._announce_event("track_end_alert", message)


def cleanup_intro_alert_player(frame, player: Player) -> None:
    for idx, (stored_player, temp_path) in enumerate(list(frame._intro_alert_players)):
        if stored_player is player:
            try:
                stored_player.stop()
            except Exception:  # pylint: disable=broad-except
                pass
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:  # pylint: disable=broad-except
                pass
            frame._intro_alert_players.pop(idx)
            break


def play_intro_alert(frame) -> bool:
    if frame._intro_alert_seconds <= 0:
        logger.debug("Intro alert: disabled (threshold=%.3f)", frame._intro_alert_seconds)
        return False
    if not frame._settings.get_announcement_enabled("intro_alert"):
        logger.debug("Intro alert: disabled via announcement settings")
        return False
    pfl_device_id = frame._playback.pfl_device_id or frame._settings.get_pfl_device()
    if not pfl_device_id:
        logger.debug("Intro alert: no PFL device configured")
        return False
    if _is_preview_active(frame):
        logger.debug("Intro alert: suppressed (PFL preview active)")
        return False
    known_devices = {device.id for device in frame._audio_engine.get_devices()}
    if pfl_device_id not in known_devices:
        frame._audio_engine.refresh_devices()
        known_devices = {device.id for device in frame._audio_engine.get_devices()}
    if pfl_device_id not in known_devices:
        logger.debug("Intro alert: PFL device unavailable id=%s", pfl_device_id)
        return False
    try:
        player = frame._audio_engine.create_player_instance(pfl_device_id)
    except Exception:  # pylint: disable=broad-except
        logger.debug("Intro alert: failed to create player for device=%s", pfl_device_id, exc_info=True)
        return False

    try:
        resource = files("sara.audio").joinpath("media", "beep.wav")
        with resource.open("rb") as source:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            tmp.write(source.read())
            tmp_path = Path(tmp.name)
    except Exception:  # pylint: disable=broad-except
        logger.debug("Intro alert: failed to load beep resource", exc_info=True)
        try:
            player.stop()
        except Exception:  # pylint: disable=broad-except
            pass
        if "tmp" in locals():
            tmp.close()
        return False
    else:
        tmp.close()

    try:
        player.set_finished_callback(lambda _item_id: wx.CallAfter(frame._cleanup_intro_alert_player, player))
        player.set_progress_callback(None)
        player.play("intro-alert", str(tmp_path), allow_loop=False)
    except Exception:  # pylint: disable=broad-except
        logger.debug("Intro alert: failed to start playback on PFL device=%s", pfl_device_id, exc_info=True)
        try:
            player.stop()
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:  # pylint: disable=broad-except
            pass
        return False

    frame._intro_alert_players.append((player, tmp_path))
    logger.debug("Intro alert: started on PFL device=%s", pfl_device_id)
    return True


def cleanup_track_end_alert_player(frame, player: Player) -> None:
    for idx, (stored_player, temp_path) in enumerate(list(frame._track_end_alert_players)):
        if stored_player is player:
            try:
                stored_player.stop()
            except Exception:  # pylint: disable=broad-except
                pass
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:  # pylint: disable=broad-except
                pass
            frame._track_end_alert_players.pop(idx)
            break


def play_track_end_alert(frame) -> bool:
    if frame._track_end_alert_seconds <= 0:
        logger.debug("Track-end alert: disabled (threshold=%.3f)", frame._track_end_alert_seconds)
        return False
    if not frame._settings.get_announcement_enabled("track_end_alert"):
        logger.debug("Track-end alert: disabled via announcement settings")
        return False
    pfl_device_id = frame._playback.pfl_device_id or frame._settings.get_pfl_device()
    if not pfl_device_id:
        logger.debug("Track-end alert: no PFL device configured")
        return False
    known_devices = {device.id for device in frame._audio_engine.get_devices()}
    if pfl_device_id not in known_devices:
        frame._audio_engine.refresh_devices()
        known_devices = {device.id for device in frame._audio_engine.get_devices()}
    if pfl_device_id not in known_devices:
        logger.debug("Track-end alert: PFL device unavailable id=%s", pfl_device_id)
        return False
    try:
        player = frame._audio_engine.create_player_instance(pfl_device_id)
    except Exception:  # pylint: disable=broad-except
        logger.debug("Track-end alert: failed to create player for device=%s", pfl_device_id, exc_info=True)
        return False

    try:
        resource = files("sara.audio").joinpath("media", "track_end_alert.wav")
        with resource.open("rb") as source:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            tmp.write(source.read())
            tmp_path = Path(tmp.name)
    except Exception:  # pylint: disable=broad-except
        logger.debug("Track-end alert: failed to load audio resource", exc_info=True)
        try:
            player.stop()
        except Exception:  # pylint: disable=broad-except
            pass
        if "tmp" in locals():
            tmp.close()
        return False
    else:
        tmp.close()

    try:
        player.set_finished_callback(lambda _item_id: wx.CallAfter(frame._cleanup_track_end_alert_player, player))
        player.set_progress_callback(None)
        player.play("track-end-alert", str(tmp_path), allow_loop=False)
    except Exception:  # pylint: disable=broad-except
        logger.debug("Track-end alert: failed to start playback on PFL device=%s", pfl_device_id, exc_info=True)
        try:
            player.stop()
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:  # pylint: disable=broad-except
            pass
        return False

    frame._track_end_alert_players.append((player, tmp_path))
    logger.debug("Track-end alert: started on PFL device=%s", pfl_device_id)
    return True


def consider_intro_alert(
    frame,
    panel: PlaylistPanel,
    item: PlaylistItem,
    context: PlaybackContext,
    absolute_seconds: float,
) -> None:
    intro_end = context.intro_seconds if context.intro_seconds is not None else item.intro_seconds
    if intro_end is None:
        return
    if item.loop_enabled:
        return
    if context.intro_alert_triggered:
        return
    threshold = frame._intro_alert_seconds
    if threshold <= 0:
        return
    remaining = intro_end - absolute_seconds
    if remaining <= 0:
        context.intro_alert_triggered = True
        return
    if remaining <= threshold:
        played = frame._play_intro_alert()
        if not played:
            logger.debug("Intro alert: audio unavailable -> announcing remaining item=%s", item.id)
            frame._announce_intro_remaining(remaining)
        context.intro_alert_triggered = True


def consider_track_end_alert(
    frame,
    panel: PlaylistPanel,
    item: PlaylistItem,
    context: PlaybackContext,
) -> None:
    if context.track_end_alert_triggered:
        return
    if item.loop_enabled:
        return
    threshold = frame._track_end_alert_seconds
    if threshold <= 0:
        return
    duration = float(item.effective_duration_seconds)
    if not item.break_after:
        playlist = panel.model
        key = (playlist.id, item.id)
        plan = getattr(frame, "_mix_plans", {}).get(key)
        if plan:
            effective = max(0.0, float(plan.effective_duration))
            mix_at = plan.mix_at
            if mix_at is None:
                duration = effective
            else:
                track_end = float(plan.base_cue) + effective
                if (track_end - float(mix_at)) <= 0.05:
                    duration = effective
                else:
                    duration = max(0.0, float(mix_at) - float(plan.base_cue))
        else:
            fade_duration = max(0.0, float(getattr(frame, "_fade_duration", 0.0) or 0.0))
            duration = compute_air_duration_seconds(item, fade_duration)
    if duration <= 0:
        logger.debug("Track-end alert: skipped (duration<=0) item=%s", item.id)
        context.track_end_alert_triggered = True
        return
    if duration < threshold:
        logger.debug(
            "Track-end alert: skipped (duration<threshold) item=%s duration=%.3f threshold=%.3f",
            item.id,
            duration,
            threshold,
        )
        context.track_end_alert_triggered = True
        return
    remaining = duration - item.current_position
    if remaining <= 0:
        context.track_end_alert_triggered = True
        return
    if remaining <= threshold:
        logger.debug(
            "Track-end alert: trigger item=%s remaining=%.3f threshold=%.3f duration=%.3f pos=%.3f",
            item.id,
            remaining,
            threshold,
            duration,
            item.current_position,
        )
        played = frame._play_track_end_alert()
        if not played:
            logger.debug("Track-end alert: audio unavailable -> announcing remaining item=%s", item.id)
            frame._announce_track_end_remaining(remaining)
        context.track_end_alert_triggered = True
