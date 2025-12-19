"""BASS ASIO helpers used by `BassManager`."""

from __future__ import annotations

import ctypes
import logging
from typing import List, TYPE_CHECKING

from sara.audio.bass.asio_native import _BASS_ASIO_DEVICEINFO
from sara.audio.bass.native import BassNotAvailable

from .contexts import _AsioDeviceContext

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from sara.audio.engine import AudioDevice
    from sara.audio.bass.manager import BassManager


def list_asio_devices(manager: "BassManager") -> List["AudioDevice"]:
    from sara.audio.engine import AudioDevice, BackendType

    devices: List[AudioDevice] = []
    try:
        manager._ensure_asio()
    except Exception:
        return devices
    idx = 0
    info = _BASS_ASIO_DEVICEINFO()
    while manager._asio._lib.BASS_ASIO_GetDeviceInfo(idx, ctypes.byref(info)):
        name = info.name.decode("utf-8", errors="ignore") if info.name else f"ASIO {idx}"
        # tworzymy standardowe pary kanałów stereo (0/1, 2/3, 4/5, 6/7)
        for ch in (0, 2, 4, 6):
            devices.append(
                AudioDevice(
                    id=f"bass-asio:{idx}:{ch}",
                    name=f"{name} ch{ch+1}-{ch+2}",
                    backend=BackendType.BASS_ASIO,
                    raw_index=idx,
                    is_default=False,
                )
            )
        idx += 1
    return devices


def acquire_asio_device(manager: "BassManager", index: int) -> _AsioDeviceContext:
    manager._ensure_asio()
    with manager._global_lock:
        data = manager._asio_devices.setdefault(index, {"ref": 0, "init": False})
        data["ref"] += 1
        if not data["init"]:
            code = manager._asio._lib.BASS_ASIO_Init(index, 0)
            if not code:
                code = manager._asio._lib.BASS_ASIO_ErrorGetCode()
                raise BassNotAvailable(f"BASS_ASIO_Init({index}) nie powiodło się (kod {code})")
            data["init"] = True
    manager._asio._lib.BASS_ASIO_SetDevice(index)
    return _AsioDeviceContext(manager, index)


def _release_asio_device(manager: "BassManager", index: int) -> None:
    if manager._asio is None:
        return
    with manager._global_lock:
        data = manager._asio_devices.get(index)
        if not data:
            return
        data["ref"] = max(0, int(data["ref"]) - 1)
        if data["ref"] <= 0 and data.get("init"):
            try:
                manager._asio._lib.BASS_ASIO_SetDevice(index)
                manager._asio._lib.BASS_ASIO_Free()
            except Exception:  # pylint: disable=broad-except
                pass
            data["init"] = False


def asio_set_device(manager: "BassManager", index: int) -> None:
    manager._ensure_asio()
    if not manager._asio._lib.BASS_ASIO_SetDevice(index):
        code = manager._asio._lib.BASS_ASIO_ErrorGetCode()
        raise BassNotAvailable(f"BASS_ASIO_SetDevice({index}) nie powiodło się (kod {code})")


def asio_channel_reset(manager: "BassManager", is_input: bool, channel: int, flags: int = 0) -> None:
    manager._ensure_asio()
    manager._asio._lib.BASS_ASIO_ChannelReset(bool(is_input), channel, flags)


def asio_channel_enable_bass(manager: "BassManager", is_input: bool, channel: int, bass_channel: int, join: bool) -> None:
    manager._ensure_asio()
    if not manager._asio._lib.BASS_ASIO_ChannelEnableBASS(bool(is_input), channel, bass_channel, bool(join)):
        code = manager._asio._lib.BASS_ASIO_ErrorGetCode()
        raise BassNotAvailable(f"BASS_ASIO_ChannelEnableBASS nie powiodło się (kod {code})")


def asio_channel_join(manager: "BassManager", is_input: bool, channel: int, join_channel: int) -> None:
    manager._ensure_asio()
    manager._asio._lib.BASS_ASIO_ChannelJoin(bool(is_input), channel, join_channel)


def asio_channel_set_volume(manager: "BassManager", is_input: bool, channel: int, volume: float) -> None:
    manager._ensure_asio()
    manager._asio._lib.BASS_ASIO_ChannelSetVolume(bool(is_input), channel, ctypes.c_float(volume))


def asio_channel_set_rate(manager: "BassManager", is_input: bool, channel: int, rate: float) -> None:
    manager._ensure_asio()
    manager._asio._lib.BASS_ASIO_ChannelSetRate(bool(is_input), channel, ctypes.c_double(rate))


def asio_start(manager: "BassManager", samplerate: float, *, index: int | None = None) -> None:
    manager._ensure_asio()
    if index is not None:
        asio_set_device(manager, index)
    if not manager._asio._lib.BASS_ASIO_Start(ctypes.c_double(samplerate)):
        code = manager._asio._lib.BASS_ASIO_ErrorGetCode()
        raise BassNotAvailable(f"BASS_ASIO_Start nie powiodło się (kod {code})")


def asio_stop(manager: "BassManager", index: int | None = None) -> None:
    try:
        manager._ensure_asio()
    except Exception:
        return
    if index is not None:
        try:
            asio_set_device(manager, index)
        except Exception:
            return
    manager._asio._lib.BASS_ASIO_Stop()


def asio_is_started(manager: "BassManager", index: int | None = None) -> bool:
    try:
        manager._ensure_asio()
    except Exception:
        return False
    if index is not None:
        try:
            asio_set_device(manager, index)
        except Exception:
            return False
    return bool(manager._asio._lib.BASS_ASIO_IsStarted())


def asio_is_active(manager: "BassManager", index: int) -> bool:
    # Compatibility alias used by `BassAsioPlayer`.
    return asio_is_started(manager, index)


def asio_set_volume(manager: "BassManager", device_index: int, channel_start: int, volume: float) -> None:
    """Set output volume for a stereo ASIO pair."""
    volume = max(0.0, min(float(volume), 1.0))
    asio_set_device(manager, device_index)
    try:
        asio_channel_set_volume(manager, False, channel_start, volume)
    except Exception as exc:
        logger.debug("BASS ASIO: volume set failed ch=%s err=%s", channel_start, exc)
    try:
        asio_channel_set_volume(manager, False, channel_start + 1, volume)
    except Exception as exc:
        logger.debug("BASS ASIO: volume set failed ch=%s err=%s", channel_start + 1, exc)


def asio_play_stream(
    manager: "BassManager",
    device_index: int,
    stream: int,
    *,
    channel_start: int = 0,
    samplerate: float = 48000.0,
) -> None:
    """Route a BASS decode stream to an ASIO output stereo pair and start rendering."""
    manager._ensure_asio()
    if not stream:
        raise BassNotAvailable("BASS ASIO stream not available")
    channel_start = max(0, int(channel_start))
    asio_set_device(manager, device_index)
    try:
        asio_channel_reset(manager, False, channel_start, 0)
        asio_channel_reset(manager, False, channel_start + 1, 0)
    except Exception:
        # reset is best-effort; continue with enabling
        pass
    try:
        asio_channel_join(manager, False, channel_start + 1, channel_start)
    except Exception:
        pass
    asio_channel_enable_bass(manager, False, channel_start, stream, False)
    if not asio_is_started(manager, device_index):
        asio_start(manager, samplerate, index=device_index)
