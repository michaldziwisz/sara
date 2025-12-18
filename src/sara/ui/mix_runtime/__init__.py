"""Mix / automix runtime logic extracted from the main frame.

This package keeps `MainFrame` smaller by grouping mix/automix runtime helpers
in focused modules while preserving the legacy `sara.ui.mix_runtime` API.
"""

from __future__ import annotations

from sara.ui.mix_runtime.callbacks import auto_mix_now_from_callback
from sara.ui.mix_runtime.now import auto_mix_now
from sara.ui.mix_runtime.progress import auto_mix_state_process
from sara.ui.mix_runtime.triggers import apply_mix_trigger_to_playback, sync_loop_mix_trigger

__all__ = [
    "apply_mix_trigger_to_playback",
    "auto_mix_now",
    "auto_mix_now_from_callback",
    "auto_mix_state_process",
    "sync_loop_mix_trigger",
]
