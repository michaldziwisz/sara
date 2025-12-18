"""Helpers for selecting the playback device/player for a playlist.

Extracted from `PlaybackController` to keep the controller easier to navigate
and to isolate the device selection logic for testing/refactoring.
"""

from __future__ import annotations

import logging

from sara.audio.engine import AudioDevice, BackendType, Player
from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistModel

logger = logging.getLogger(__name__)


def _pick_fallback(device_map: dict[str, AudioDevice], busy_devices: set[str]) -> tuple[int, str] | None:
    # prefer BASS not busy -> any not busy -> busy BASS -> any
    def score(dev: AudioDevice) -> tuple[int, bool]:
        return (0 if dev.backend is BackendType.BASS else 1, dev.id in busy_devices)

    sorted_devices = sorted(device_map.values(), key=score)
    for dev in sorted_devices:
        if dev.id in busy_devices:
            continue
        return (0, dev.id)
    if sorted_devices:
        return (0, sorted_devices[0].id)
    return None


def ensure_player(controller, playlist: PlaylistModel) -> tuple[Player, str, int] | None:
    attempts = 0
    missing_devices: set[str] = set()
    use_mixer = controller._should_use_mixer(playlist)

    while attempts < 2:
        devices = controller._audio_engine.get_devices()
        if not devices:
            controller._audio_engine.refresh_devices()
            devices = controller._audio_engine.get_devices()
            if not devices:
                controller._announce("device", _("No audio devices available"))
                return None

        device_map = {device.id: device for device in devices}
        busy_devices = controller.get_busy_device_ids()
        selection = playlist.select_next_slot(set(device_map.keys()), busy_devices)
        if selection is None:
            selection = _pick_fallback(device_map, busy_devices)
            if selection is None:
                logger.error(
                    "PlaybackController: no available slot for playlist=%s configured_slots=%s available=%s busy=%s",
                    playlist.name,
                    playlist.get_configured_slots(),
                    list(device_map.keys()),
                    list(busy_devices),
                )
                if playlist.get_configured_slots():
                    controller._announce(
                        "device",
                        _("No configured player for playlist %s is available") % playlist.name,
                    )
                return None

        slot_index, device_id = selection
        device = device_map.get(device_id)
        if device is None:
            missing_devices.add(device_id)
            if playlist.output_slots and 0 <= slot_index < len(playlist.output_slots):
                playlist.output_slots[slot_index] = None
                controller._settings.set_playlist_outputs(playlist.name, playlist.output_slots)
                controller._settings.save()
            attempts += 1
            controller._audio_engine.refresh_devices()
            logger.debug(
                "PlaybackController: device %s missing for playlist=%s, refreshing devices (attempt %s)",
                device_id,
                playlist.name,
                attempts,
            )
            continue

        logger.debug(
            "PlaybackController: selected device %s backend=%s slot=%s use_mixer=%s configured_slots=%s busy=%s",
            device_id,
            device.backend if hasattr(device, "backend") else "?",
            slot_index,
            use_mixer,
            playlist.get_configured_slots(),
            busy_devices,
        )

        try:
            # Jeśli backend to BASS lub mixer nie jest dostępny, graj bezpośrednio
            effective_use_mixer = use_mixer and device.backend not in (BackendType.BASS, BackendType.BASS_ASIO)
            player: Player
            if effective_use_mixer:
                try:
                    mixer = controller._get_or_create_mixer(device)
                    MixerPlayer = controller._get_mixer_player_class()
                    player = MixerPlayer(mixer)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("Mixer unavailable for %s, falling back to direct player: %s", device_id, exc)
                    effective_use_mixer = False
            if not effective_use_mixer:
                player = controller._audio_engine.create_player(device_id)
            return player, device_id, slot_index
        except ValueError:
            attempts += 1
            controller._audio_engine.refresh_devices()

    if missing_devices:
        removed_list = ", ".join(sorted(missing_devices))
        controller._announce(
            "device",
            _("Unavailable devices for playlist %s: %s") % (playlist.name, removed_list),
        )
    return None

