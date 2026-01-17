"""Backward-compatible import path for Sygnalista feedback dialog.

The implementation lives in `sara.ui.dialogs.feedback.dialog`.
"""

from __future__ import annotations

from sara.ui.dialogs.feedback_dialog import FeedbackDialog

__all__ = [
    "FeedbackDialog",
]
