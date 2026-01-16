"""Stream + channel helpers used by `BassManager`."""

from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from sara.audio.bass.native import BassNotAvailable, _BassConstants

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from sara.audio.bass.manager import BassManager


def stream_create_file(
    manager: "BassManager",
    index: int,
    path: Path,
    *,
    allow_loop: bool = False,
    decode: bool = False,
    set_device: bool = True,
) -> int:
    if set_device:
        manager._set_device(index)
    flags = _BassConstants.SAMPLE_FLOAT | _BassConstants.STREAM_PRESCAN
    if os.environ.get("SARA_BASS_ASYNCFILE", "1") not in {"0", "false", "False"}:
        flags |= _BassConstants.ASYNCFILE
    if allow_loop:
        flags |= _BassConstants.SAMPLE_LOOP
    if decode:
        flags |= _BassConstants.STREAM_DECODE
    if manager._stream_create_file is None:
        raise BassNotAvailable("BASS_StreamCreateFile not available")
    stream = 0
    try:
        if manager._stream_uses_wchar:
            stream = manager._stream_create_file(
                False,
                ctypes.c_wchar_p(str(path)),
                0,
                0,
                flags | _BassConstants.UNICODE,
            )
        else:
            stream = manager._stream_create_file(False, str(path).encode("utf-8"), 0, 0, flags)
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("BASS stream create error: %s", exc)
    if not stream:
        last_code = manager._lib.BASS_ErrorGetCode()
        logger.error(
            "BASS_StreamCreateFile failed code=%s device=%s path=%s wide=%s",
            last_code,
            index,
            path,
            manager._stream_uses_wchar,
        )
        raise BassNotAvailable(f"BASS_StreamCreateFile nie powiodło się (kod {last_code})")
    return stream


def stream_free(manager: "BassManager", stream: int) -> None:
    if stream:
        manager._lib.BASS_StreamFree(stream)


def channel_play(manager: "BassManager", stream: int, restart: bool = False) -> None:
    if not manager._lib.BASS_ChannelPlay(stream, restart):
        code = manager._lib.BASS_ErrorGetCode()
        raise BassNotAvailable(f"BASS_ChannelPlay nie powiodło się (kod {code})")


def channel_pause(manager: "BassManager", stream: int) -> None:
    manager._lib.BASS_ChannelPause(stream)


def channel_stop(manager: "BassManager", stream: int) -> None:
    manager._lib.BASS_ChannelStop(stream)


def channel_set_position(manager: "BassManager", stream: int, seconds: float) -> None:
    pos = manager._lib.BASS_ChannelSeconds2Bytes(stream, ctypes.c_double(seconds))
    manager._lib.BASS_ChannelSetPosition(stream, pos, _BassConstants.POS_BYTE)


def channel_get_seconds(manager: "BassManager", stream: int) -> float:
    pos = manager._lib.BASS_ChannelGetPosition(stream, _BassConstants.POS_BYTE)
    return float(manager._lib.BASS_ChannelBytes2Seconds(stream, pos))


def channel_is_active(manager: "BassManager", stream: int) -> bool:
    state = manager._lib.BASS_ChannelIsActive(stream)
    return state != _BassConstants.ACTIVE_STOPPED


def channel_get_length_seconds(manager: "BassManager", stream: int) -> float:
    pos = manager._lib.BASS_ChannelGetLength(stream, _BassConstants.POS_BYTE)
    return float(manager._lib.BASS_ChannelBytes2Seconds(stream, pos))


def channel_set_volume(manager: "BassManager", stream: int, volume: float) -> None:
    # BASS supports values above 1.0 for amplification (see vendor docs: BASS_ATTRIB_VOL).
    volume = max(0.0, float(volume))
    manager._lib.BASS_ChannelSetAttribute(stream, _BassConstants.ATTRIB_VOL, ctypes.c_float(volume))


def seconds_to_bytes(manager: "BassManager", stream: int, seconds: float) -> int:
    return int(manager._lib.BASS_ChannelSeconds2Bytes(stream, ctypes.c_double(seconds)))


def channel_set_position_bytes(manager: "BassManager", stream: int, byte_pos: int) -> None:
    manager._lib.BASS_ChannelSetPosition(stream, byte_pos, _BassConstants.POS_BYTE)


def make_sync_proc(manager: "BassManager", func: Callable[[int, int, int, ctypes.c_void_p], None]):
    return manager._sync_type(func)


def channel_set_sync_pos(
    manager: "BassManager",
    stream: int,
    position_or_seconds: float,
    proc,
    *,
    is_bytes: bool = False,
    mix_time: bool = True,
) -> int:
    position = int(position_or_seconds) if is_bytes else seconds_to_bytes(manager, stream, float(position_or_seconds))
    flags = _BassConstants.SYNC_POS | (_BassConstants.SYNC_MIXTIME if mix_time else 0)
    handle = manager._lib.BASS_ChannelSetSync(stream, flags, position, proc, None)
    if not handle:
        code = manager._lib.BASS_ErrorGetCode()
        raise BassNotAvailable(f"BASS_ChannelSetSync nie powiodło się (kod {code})")
    return handle


def channel_remove_sync(manager: "BassManager", stream: int, sync_handle: int) -> None:
    if sync_handle:
        manager._lib.BASS_ChannelRemoveSync(stream, sync_handle)


def channel_set_sync_end(manager: "BassManager", stream: int, proc) -> int:
    handle = manager._lib.BASS_ChannelSetSync(
        stream,
        _BassConstants.SYNC_END | _BassConstants.SYNC_MIXTIME,
        0,
        proc,
        None,
    )
    if not handle:
        code = manager._lib.BASS_ErrorGetCode()
        raise BassNotAvailable(f"BASS_ChannelSetSync (END) nie powiodło się (kod {code})")
    return handle
