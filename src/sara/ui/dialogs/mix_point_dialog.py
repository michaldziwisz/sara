"""Backward-compatible module path for `MixPointEditorDialog`.

The implementation lives in `sara.ui.dialogs.mix_point.dialog`.
"""

from __future__ import annotations

import sys as _sys

from sara.ui.dialogs.mix_point import dialog as _impl

_sys.modules[__name__] = _impl

