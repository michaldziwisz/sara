"""Start-item helpers extracted from `PlaybackController`."""

from __future__ import annotations

import logging
from typing import Callable

from sara.audio.engine import Player
from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistModel
from sara.ui.playback_context import PlaybackContext

logger = logging.getLogger(__name__)


def start_item_impl(
    controller,
    playlist: PlaylistModel,
    item: PlaylistItem,
    *,
    start_seconds: float,
    on_finished: Callable[[str], None],
    on_progress: Callable[[str, float], None],
    restart_if_playing: bool = False,
    mix_trigger_seconds: float | None = None,
    on_mix_trigger: Callable[[], None] | None = None,
) -> PlaybackContext | None:
    # Nie uruchamiaj ponownie utworu już zagranych (PLAYED), chyba że wyraźnie prosimy o restart.
    if item.status is PlaylistItemStatus.PLAYED:
        if restart_if_playing:
            logger.debug(
                "PlaybackController: restarting item marked PLAYED playlist=%s item=%s",
                playlist.name,
                item.id,
            )
            # pozwól na ponowne zagranie jakby był świeży
            item.status = PlaylistItemStatus.PENDING
        else:
            logger.debug(
                "PlaybackController: skipping item already PLAYED playlist=%s item=%s",
                playlist.name,
                item.id,
            )
            return None
    logger.info(
        "PlaybackController: start_item playlist=%s item_id=%s title=%s slots=%s busy=%s",
        playlist.name,
        item.id,
        getattr(item, "title", item.id),
        playlist.get_configured_slots(),
        controller.get_busy_device_ids(),
    )
    key = (playlist.id, item.id)
    context = controller._playback_contexts.get(key)
    player = context.player if context else None
    device_id = context.device_id if context else None
    slot_index = context.slot_index if context else None

    if (
        player is not None
        and device_id is not None
        and slot_index is not None
        and item.status is PlaylistItemStatus.PLAYING
    ):
        if restart_if_playing:
            logger.debug(
                "PlaybackController: restarting item already playing on device=%s slot=%s",
                device_id,
                slot_index,
            )
            try:
                player.stop()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Failed to stop player for restart: %s", exc)
        else:
            logger.debug(
                "PlaybackController: item already playing, reusing existing player device=%s slot=%s",
                device_id,
                slot_index,
            )
            return context
    # Jeśli utwór był PLAYED i automix włączony – nie restartuj go, wybierz inny.
    if (
        player is not None
        and device_id is not None
        and slot_index is not None
        and item.status is PlaylistItemStatus.PLAYED
        and controller._settings.get_alternate_play_next()
    ):
        logger.debug("PlaybackController: skipping PLAYED item in automix/play-next flow")
        return None

    if player is None or device_id is None or slot_index is None:
        acquired = controller._ensure_player(playlist)
        if acquired is None:
            logger.error("PlaybackController: no player acquired for playlist=%s item=%s", playlist.name, item.id)
            return None
        player, device_id, slot_index = acquired

        try:
            player.set_finished_callback(on_finished)
            player.set_progress_callback(on_progress)
        except Exception as exc:  # pylint: disable=broad-except
            controller._announce("playback_errors", _("Failed to assign playback callbacks: %s") % exc)
            logger.debug(
                "PlaybackController: callback assignment failed device=%s slot=%s: %s",
                device_id,
                slot_index,
                exc,
            )
            return None

    def _do_play(p: Player) -> None:
        supports_mix_trigger = controller.supports_mix_trigger(p)
        # wyzeruj ewentualne poprzednie ustawienia pętli zanim wystartujemy nowy utwór
        if hasattr(p, "set_loop") and not (item.loop_enabled and item.has_loop()):
            try:
                p.set_loop(None, None)
            except Exception:
                pass
        p.play(
            item.id,
            str(item.path),
            start_seconds=start_seconds,
            # pozwól SAMPLE_LOOP, jeśli faktycznie mamy pętlę (dla ASIO też),
            # reszta i tak jest kontrolowana markerami/guardem
            allow_loop=bool(item.loop_enabled and item.has_loop()),
            # mikser/punkty miksu: użyj bardziej precyzyjnego wyzwalacza (ms), jeśli dostępny
            mix_trigger_seconds=mix_trigger_seconds if supports_mix_trigger else None,
            on_mix_trigger=on_mix_trigger if supports_mix_trigger else None,
        )

    # Ustaw ReplayGain przed startem, żeby uniknąć „głośnego pierwszego uderzenia”
    try:
        player.set_gain_db(item.replay_gain_db)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Failed to set ReplayGain: %s", exc)

    try:
        _do_play(player)
    except Exception as exc:  # pylint: disable=broad-except
        player.set_finished_callback(None)
        player.set_progress_callback(None)
        logger.exception(
            "PlaybackController: play failed playlist=%s item=%s device=%s slot=%s err=%s",
            playlist.name,
            item.title,
            device_id,
            slot_index,
            exc,
        )
        # jeśli player jest stary/niekompletny, usuń cache i spróbuj raz jeszcze
        try:
            controller._audio_engine._players.pop(device_id, None)  # pylint: disable=protected-access
        except Exception:
            pass
        try:
            player = controller._audio_engine.create_player(device_id)
            player.set_finished_callback(on_finished)
            player.set_progress_callback(on_progress)
            # ponownie ustaw RG przed startem
            player.set_gain_db(item.replay_gain_db)
            _do_play(player)
        except Exception as retry_exc:  # pylint: disable=broad-except
            logger.exception("PlaybackController: retry after player refresh failed: %s", retry_exc)
            controller._announce("playback_errors", f"{retry_exc}")
            return None

    try:
        if hasattr(player, "set_loop"):
            if item.loop_enabled and item.has_loop():
                player.set_loop(item.loop_start_seconds, item.loop_end_seconds)
            else:
                player.set_loop(None, None)
        else:
            logger.debug("Loop not supported by player %s", type(player))
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Failed to configure loop: %s", exc)

    context = PlaybackContext(
        player=player,
        path=item.path,
        device_id=device_id,
        slot_index=slot_index,
        intro_seconds=item.intro_seconds,
    )
    controller._playback_contexts[key] = context
    controller._auto_mix_state.pop(key, None)
    return context

