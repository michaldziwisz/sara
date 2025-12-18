"""Mixer-related helpers extracted from `PlaybackController`."""

from __future__ import annotations

import logging

from sara.audio.engine import AudioDevice
from sara.core.playlist import PlaylistModel


logger = logging.getLogger(__name__)


class PlaybackMixerSupportMixin:
    def _get_mixer_classes(self):
        from sara.audio.mixer import DeviceMixer, MixerPlayer

        return DeviceMixer, MixerPlayer

    def _get_mixer_player_class(self):
        _, MixerPlayer = self._get_mixer_classes()
        return MixerPlayer

    def _default_mixer_factory(self, device: AudioDevice):
        DeviceMixer, _ = self._get_mixer_classes()
        return DeviceMixer(device)

    def _get_or_create_mixer(self, device: AudioDevice):
        mixer = self._mixers.get(device.id)
        if mixer:
            return mixer
        mixer = self._mixer_factory(device)
        self._mixers[device.id] = mixer
        return mixer

    def _cleanup_unused_mixers(self) -> None:
        active_devices = {context.device_id for context in self._playback_contexts.values()}
        stale = [device_id for device_id in self._mixers if device_id not in active_devices]
        for device_id in stale:
            mixer = self._mixers.pop(device_id)
            try:
                mixer.close()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Nie udało się zamknąć miksera %s: %s", device_id, exc)

    def _should_use_mixer(self, playlist: PlaylistModel) -> bool:
        slots = [slot for slot in playlist.get_configured_slots() if slot]
        return len(slots) <= 1

