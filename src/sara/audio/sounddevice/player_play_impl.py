"""Sounddevice play() implementation helper.

This module exists to keep `player_base.py` smaller and easier to read.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import Event, Thread
from typing import TYPE_CHECKING, Callable, Dict, Optional

from sara.audio.resampling import _resample_to_length

if TYPE_CHECKING:
    from .player_base import SoundDevicePlayer


def play_impl(  # noqa: PLR0915
    player: "SoundDevicePlayer",
    playlist_item_id: str,
    source_path: str,
    *,
    start_seconds: float = 0.0,
    allow_loop: bool = True,
    mix_trigger_seconds: float | None = None,
    on_mix_trigger: Callable[[], None] | None = None,
    sd,
    np,
    logger: logging.Logger,
) -> Event:  # noqa: D401
    del allow_loop, mix_trigger_seconds, on_mix_trigger

    path = Path(source_path)
    with player._lock:
        if player._current_item == playlist_item_id:
            return player._finished_event or Event()
        player.stop()
        player._current_item = playlist_item_id
        player._path = path
        try:
            sound_file = player._open_audio_file(path)
        except Exception as exc:  # pylint: disable=broad-except
            player._current_item = None
            raise RuntimeError(f"Nie udało się otworzyć pliku audio: {exc}") from exc

        samplerate = sound_file.samplerate
        channels = sound_file.channels
        stream_kwargs = dict(player._stream_kwargs)
        output_samplerate = float(samplerate)
        resample_ratio = 1.0
        resample_state = {"src_pos": 0.0, "dst_pos": 0.0}
        device_info: Dict[str, object] = {}
        if sd is not None and player.device.raw_index is not None:
            try:
                device_info = sd.query_devices(player.device.raw_index)
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("Nie udało się pobrać informacji o urządzeniu: %s", exc)
                device_info = {}
            try:
                host_index_raw = device_info.get("hostapi")
                host_index = int(host_index_raw) if host_index_raw is not None else -1
            except Exception:  # pylint: disable=broad-except
                host_index = -1
            if host_index >= 0:
                try:
                    host_name = sd.query_hostapis()[host_index]["name"].lower()
                    if "wasapi" in host_name and "extra_settings" not in stream_kwargs:
                        stream_kwargs["extra_settings"] = sd.WasapiSettings(exclusive=False)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.debug("Nie udało się skonfigurować ustawień WASAPI: %s", exc)

            try:
                sd.check_output_settings(
                    device=player.device.raw_index,
                    samplerate=output_samplerate,
                    channels=channels,
                )
            except Exception:
                fallback_rate: Optional[float] = None
                try:
                    fallback_raw = device_info.get("default_samplerate")
                    if fallback_raw:
                        fallback_rate = float(fallback_raw)
                except Exception:  # pylint: disable=broad-except
                    fallback_rate = None
                if fallback_rate and samplerate and fallback_rate != samplerate:
                    output_samplerate = fallback_rate
                    resample_ratio = output_samplerate / float(samplerate)
                    try:
                        sd.check_output_settings(
                            device=player.device.raw_index,
                            samplerate=output_samplerate,
                            channels=channels,
                        )
                    except Exception as exc:  # pylint: disable=broad-except
                        raise RuntimeError(
                            "Urządzenie PFL nie obsługuje wymaganej częstotliwości próbkowania"
                        ) from exc
                else:
                    raise RuntimeError("Urządzenie PFL nie obsługuje częstotliwości próbkowania pliku")
        player._stop_event = Event()
        player._pause_event = Event()
        player._finished_event = Event()
        stop_event = player._stop_event
        player._current_item = playlist_item_id
        player._path = path
        player._samplerate = samplerate
        player._total_frames = len(sound_file)

        start_frame = int(max(0.0, start_seconds) * samplerate)
        if start_frame >= player._total_frames and player._total_frames > 0:
            start_frame = max(player._total_frames - 1, 0)
        player._position = start_frame

        if player._position:
            try:
                sound_file.seek(player._position)
            except Exception:
                player._position = 0
                sound_file.seek(0)

        player._apply_loop_request(samplerate)

        def _run() -> None:
            with sound_file:
                restart_attempted = False
                while True:
                    try:
                        with sd.OutputStream(
                            device=player.device.raw_index,
                            samplerate=output_samplerate,
                            channels=channels,
                            dtype="float32",
                            **stream_kwargs,
                        ) as stream:
                            block = 4096
                            while stop_event is not None and not stop_event.is_set():
                                if player._pause_event.is_set():
                                    time.sleep(0.05)
                                    continue
                                data = sound_file.read(block, dtype="float32", always_2d=True)
                                frames_read = len(data)
                                if data.size == 0:
                                    with player._lock:
                                        loop_active = player._loop_active
                                        loop_start_frame = player._loop_start_frame
                                        loop_end_frame = player._loop_end_frame
                                    if loop_active and loop_end_frame > loop_start_frame:
                                        sound_file.seek(loop_start_frame)
                                        player._position = loop_start_frame
                                        continue
                                    break
                                with player._lock:
                                    gain_factor = player._gain_factor
                                    loop_active = player._loop_active
                                    loop_start_frame = player._loop_start_frame
                                    loop_end_frame = player._loop_end_frame
                                output_block = data
                                if gain_factor != 1.0:
                                    output_block = output_block * gain_factor
                                if frames_read and abs(resample_ratio - 1.0) > 1e-6:
                                    resample_state["src_pos"] += frames_read
                                    expected_total = resample_state["src_pos"] * resample_ratio
                                    target_frames = int(round(expected_total - resample_state["dst_pos"]))
                                    target_frames = max(1, target_frames)
                                    output_block = _resample_to_length(output_block, target_frames)
                                    resample_state["dst_pos"] += len(output_block)
                                if np is not None and player._pending_fade_in > 0 and len(output_block):
                                    frames = min(len(output_block), player._pending_fade_in)
                                    fade = np.linspace(0.0, 1.0, frames, endpoint=False, dtype=output_block.dtype)
                                    output_block = output_block.copy()
                                    output_block[:frames] *= fade[:, None]
                                    player._pending_fade_in = max(0, player._pending_fade_in - frames)
                                will_loop = (
                                    loop_active
                                    and loop_end_frame > loop_start_frame
                                    and player._position + frames_read >= loop_end_frame
                                )
                                if will_loop and np is not None and len(output_block):
                                    fade_frames = min(len(output_block), max(1, int(output_samplerate * 0.003)))
                                    fade = np.linspace(1.0, 0.0, fade_frames, endpoint=False, dtype=output_block.dtype)
                                    output_block = output_block.copy()
                                    output_block[-fade_frames:] *= fade[:, None]
                                    player._pending_fade_in = fade_frames
                                stream.write(output_block)
                                player._position += frames_read
                                if (
                                    loop_active
                                    and loop_end_frame > loop_start_frame
                                    and player._position >= loop_end_frame
                                ):
                                    try:
                                        sound_file.seek(loop_start_frame)
                                    except Exception as exc:  # pylint: disable=broad-except
                                        logger.error("Błąd ustawienia pętli: %s", exc)
                                        with player._lock:
                                            player._loop_active = False
                                    else:
                                        player._position = loop_start_frame
                                        continue
                                if player._on_progress:
                                    seconds = player._position / player._samplerate if player._samplerate else 0.0
                                    try:
                                        player._on_progress(player._current_item or playlist_item_id, seconds)
                                    except Exception as exc:  # pylint: disable=broad-except
                                        logger.error("Błąd callbacku postępu: %s", exc)
                        break
                    except Exception as exc:  # pylint: disable=broad-except
                        should_retry = False
                        status_code = getattr(exc, "errno", None) or getattr(exc, "status", None)
                        if (
                            sd is not None
                            and isinstance(exc, Exception)
                            and status_code == -9983
                            and not restart_attempted
                            and stop_event is not None
                            and not stop_event.is_set()
                        ):
                            restart_attempted = True
                            should_retry = True
                            logger.warning(
                                "Strumień sounddevice zatrzymany (PaError -9983) na %s, ponawiam...",
                                player.device.name,
                            )
                            time.sleep(0.05)
                        if not should_retry:
                            logger.error("Błąd odtwarzania sounddevice: %s", exc)
                            break
                    if not restart_attempted:
                        break
                should_notify = not stop_event.is_set() if stop_event else True
                current_item = player._current_item
                player._position = 0
                if player._finished_event:
                    player._finished_event.set()
                player._current_item = None
                if player._on_progress and current_item:
                    try:
                        total = player._total_frames / player._samplerate if player._samplerate else 0.0
                        player._on_progress(current_item, total)
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.error("Błąd callbacku postępu: %s", exc)
                if should_notify and current_item and player._on_finished:
                    try:
                        player._on_finished(current_item)
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.error("Błąd callbacku zakończenia odtwarzania: %s", exc)
                player._cleanup_transcoded_file()

        player._thread = Thread(target=_run, daemon=True)
        player._thread.start()
        return player._finished_event

