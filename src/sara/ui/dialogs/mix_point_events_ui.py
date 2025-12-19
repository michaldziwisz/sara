"""Backward-compatible module path for mix point dialog event helpers."""

from __future__ import annotations

import sys as _sys

from sara.ui.dialogs.mix_point import events_ui as _impl

_sys.modules[__name__] = _impl

