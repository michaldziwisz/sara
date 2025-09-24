"""Abstraction over keyboard shortcuts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class HotkeyAction:
    key: str
    description: str | None = None
    handler: Optional[Callable[[], None]] = None

    def trigger(self) -> None:
        if self.handler:
            self.handler()
