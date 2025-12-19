"""Backward-compatible module path for mix point loudness UI helpers."""

from __future__ import annotations

import sys as _sys

from sara.ui.dialogs.mix_point import loudness_ui as _impl

_sys.modules[__name__] = _impl

