"""Intro/track-end alert helpers extracted from the main frame."""

from __future__ import annotations

from importlib.resources import files
import logging
import tempfile
from pathlib import Path

import wx

from sara.audio.engine import Player
from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem
from sara.ui.playback_controller import PlaybackContext
from sara.ui.playlist_panel import PlaylistPanel


logger = logging.getLogger(__name__)


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
        return False
    if not frame._settings.get_announcement_enabled("intro_alert"):
        return False
    pfl_device_id = frame._playback.pfl_device_id or frame._settings.get_pfl_device()
    if not pfl_device_id:
        return False
    if frame._playback.preview_context:
        return False
    known_devices = {device.id for device in frame._audio_engine.get_devices()}
    if pfl_device_id not in known_devices:
        frame._audio_engine.refresh_devices()
        known_devices = {device.id for device in frame._audio_engine.get_devices()}
    if pfl_device_id not in known_devices:
        return False
    try:
        player = frame._audio_engine.create_player(pfl_device_id)
    except Exception:  # pylint: disable=broad-except
        return False

    try:
        resource = files("sara.audio.media").joinpath("beep.wav")
        with resource.open("rb") as source:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            tmp.write(source.read())
            tmp_path = Path(tmp.name)
    except Exception:  # pylint: disable=broad-except
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
        return False
    if not frame._settings.get_announcement_enabled("track_end_alert"):
        return False
    pfl_device_id = frame._playback.pfl_device_id or frame._settings.get_pfl_device()
    if not pfl_device_id:
        return False
    if frame._playback.preview_context:
        return False
    known_devices = {device.id for device in frame._audio_engine.get_devices()}
    if pfl_device_id not in known_devices:
        frame._audio_engine.refresh_devices()
        known_devices = {device.id for device in frame._audio_engine.get_devices()}
    if pfl_device_id not in known_devices:
        return False
    try:
        player = frame._audio_engine.create_player(pfl_device_id)
    except Exception:  # pylint: disable=broad-except
        return False

    try:
        resource = files("sara.audio.media").joinpath("track_end_alert.wav")
        with resource.open("rb") as source:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            tmp.write(source.read())
            tmp_path = Path(tmp.name)
    except Exception:  # pylint: disable=broad-except
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
            frame._announce_intro_remaining(remaining)
        context.intro_alert_triggered = True


def consider_track_end_alert(
    frame,
    _panel: PlaylistPanel,
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
    duration = item.effective_duration_seconds
    if duration <= 0:
        context.track_end_alert_triggered = True
        return
    if duration < threshold:
        context.track_end_alert_triggered = True
        return
    remaining = duration - item.current_position
    if remaining <= 0:
        context.track_end_alert_triggered = True
        return
    if remaining <= threshold:
        played = frame._play_track_end_alert()
        if not played:
            frame._announce_track_end_remaining(remaining)
        context.track_end_alert_triggered = True

