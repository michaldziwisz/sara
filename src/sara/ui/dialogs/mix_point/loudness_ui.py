"""UI mixin for loudness normalization in the mix point dialog."""

from __future__ import annotations

import logging

import wx

from sara.core.i18n import gettext as _
from sara.core.loudness import LoudnessStandard, find_bs1770gain
from .loudness import compute_normalization_gain
from sara.ui.speech import speak_text


logger = logging.getLogger(__name__)


class MixPointLoudnessMixin:
    def _format_replay_gain_text(self) -> str:
        if self._current_replay_gain is None:
            return _("not set")
        return _("{gain:+.2f} dB").format(gain=self._current_replay_gain)

    def _update_replay_gain_display(self) -> None:
        if hasattr(self, "_replay_gain_display"):
            self._replay_gain_display.ChangeValue(self._format_replay_gain_text())

    def _initial_loudness_status(self) -> str:
        if self._current_replay_gain is None:
            return _("ReplayGain not measured yet")
        return _("Existing ReplayGain: {gain:+.2f} dB").format(gain=self._current_replay_gain)

    def _handle_normalize(self, _event: wx.CommandEvent) -> None:
        if self._normalizing:
            return
        if find_bs1770gain() is None:
            wx.MessageBox(
                _("bs1770gain is not available. Install it and ensure it is on PATH."),
                _("Error"),
                parent=self,
            )
            return
        self._normalizing = True
        self._normalize_button.Enable(False)
        self._set_loudness_status(_("Analyzing loudness…"))
        import threading

        threading.Thread(target=self._normalization_worker, daemon=True).start()

    def _normalization_worker(self) -> None:
        try:
            standard = self._selected_standard()
            gain, measured_lufs = compute_normalization_gain(self._track_path, standard=standard)
        except Exception as exc:  # pylint: disable=broad-except
            wx.CallAfter(self._on_normalize_error, str(exc))
        else:
            wx.CallAfter(self._on_normalize_success, gain, measured_lufs)

    def _on_normalize_success(self, gain_db: float, measured_lufs: float) -> None:
        self._normalizing = False
        self._normalize_button.Enable(True)
        self._current_replay_gain = gain_db
        self._update_replay_gain_display()
        self._set_loudness_status(
            _("Measured {lufs:.2f} LUFS, applied gain {gain:+.2f} dB").format(
                lufs=measured_lufs,
                gain=gain_db,
            ),
            speak=True,
        )
        if self._on_replay_gain_update:
            self._on_replay_gain_update(gain_db)

    def _on_normalize_error(self, message: str) -> None:
        self._normalizing = False
        self._normalize_button.Enable(True)
        self._set_loudness_status(message, speak=True)
        wx.MessageBox(message or _("Normalization failed"), _("Error"), parent=self)

    def _set_loudness_status(self, message: str, *, speak: bool = False) -> None:
        if hasattr(self, "_normalize_status"):
            self._normalize_status.ChangeValue(message)
        if speak and message:
            speak_text(message)

    def _selected_standard(self) -> LoudnessStandard:
        if self._standard_radio.GetSelection() == 1:
            return LoudnessStandard.ATSC
        return LoudnessStandard.EBU
