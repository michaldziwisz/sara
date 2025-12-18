"""Context objects returned by `BassManager` acquire methods."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from sara.audio.bass.manager import BassManager


class _DeviceContext:
    def __init__(self, manager: "BassManager", index: int):
        self._manager = manager
        self.index = index

    def release(self) -> None:
        self._manager._release_device(self.index)


class _AsioDeviceContext:
    def __init__(self, manager: "BassManager", index: int):
        self._manager = manager
        self.index = index

    def release(self) -> None:
        self._manager._release_asio_device(self.index)

