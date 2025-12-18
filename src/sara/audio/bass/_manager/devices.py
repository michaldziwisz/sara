"""BASS device lifecycle helpers used by `BassManager`."""

from __future__ import annotations

import ctypes
from typing import List, TYPE_CHECKING

from sara.audio.bass.native import BassNotAvailable, _BassConstants, _BASS_DEVICEINFO

from .contexts import _DeviceContext

if TYPE_CHECKING:  # pragma: no cover
    from sara.audio.engine import AudioDevice
    from sara.audio.bass.manager import BassManager


def acquire_device(manager: "BassManager", index: int) -> _DeviceContext:
    with manager._global_lock:
        data = manager._devices.setdefault(index, {"ref": 0, "init": False})
        data["ref"] += 1
        if not data["init"]:
            code = manager._lib.BASS_Init(index, 48000, 0, None, None)
            if not code:
                code = manager._lib.BASS_ErrorGetCode()
                raise BassNotAvailable(f"BASS_Init({index}) nie powiodło się (kod {code})")
            data["init"] = True
    manager._set_device(index)
    return _DeviceContext(manager, index)


def _release_device(manager: "BassManager", index: int) -> None:
    with manager._global_lock:
        data = manager._devices.get(index)
        if not data:
            return
        data["ref"] = max(0, int(data["ref"]) - 1)
        if data["ref"] <= 0 and data.get("init"):
            try:
                manager._set_device(index)
                manager._lib.BASS_Free()
            except Exception:  # pylint: disable=broad-except
                pass
            data["init"] = False


def list_devices(manager: "BassManager") -> List["AudioDevice"]:
    from sara.audio.engine import AudioDevice, BackendType

    devices: List[AudioDevice] = []
    index = 0
    info = _BASS_DEVICEINFO()
    while manager._lib.BASS_GetDeviceInfo(index, ctypes.byref(info)):
        name = info.name.decode("utf-8", errors="ignore") if info.name else f"Device {index}"
        flags = int(info.flags or 0)
        is_default = bool(flags & _BassConstants.DEVICE_DEFAULT)
        enabled = bool(flags & _BassConstants.DEVICE_ENABLED)
        if enabled:
            devices.append(
                AudioDevice(
                    id=f"bass:{index}",
                    name=name,
                    backend=BackendType.BASS,
                    raw_index=index,
                    is_default=is_default,
                )
            )
        index += 1
    return devices

