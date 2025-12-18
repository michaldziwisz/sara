"""Standalone editor for news services."""

from __future__ import annotations

import sys
from pathlib import Path

import wx

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from sara.core.config import SettingsManager
from sara.core.i18n import gettext as _, set_language
from sara.core.playlist import PlaylistKind, PlaylistModel
from sara.audio.engine import AudioEngine
from sara.ui.news_playlist_panel import NewsPlaylistPanel
from sara.ui.playback_controller import PlaybackController
from sara.ui.controllers.news_audio import news_device_entries, preview_news_clip
from sara.news_editor_settings import NewsEditorSettings


class NewsEditorFrame(wx.Frame):
    """Minimal frame hosting the news playlist panel."""

    def __init__(self, settings: SettingsManager) -> None:
        super().__init__(None, title=_("SARA News Editor"))
        self._settings = settings
        self._audio_engine = AudioEngine()
        self._editor_settings = NewsEditorSettings()
        self._line_length = self._editor_settings.get_line_length(self._settings.get_news_line_length())
        self._model = PlaylistModel(id="news-editor", name=_("News service"), kind=PlaylistKind.NEWS)
        self._preview_controller = PlaybackController(self._audio_engine, self._settings, self._preview_announce)
        last_device = self._editor_settings.get_last_device_id()
        if last_device:
            self._model.output_device = last_device
        self._panel = NewsPlaylistPanel(
            self,
            model=self._model,
            get_line_length=lambda: self._line_length,
            get_audio_devices=self._news_device_entries,
            on_focus=lambda _playlist_id: None,
            on_play_audio=self._on_play_audio,
            on_device_change=self._on_device_changed,
            enable_line_length_control=True,
            line_length_bounds=(0, 500),
            on_line_length_change=self._on_line_length_change,
            on_line_length_apply=self._persist_editor_preferences,
            on_preview_audio=self._preview_news_clip,
            on_stop_preview_audio=lambda: self._preview_controller.stop_preview(),
        )
        root_sizer = wx.BoxSizer(wx.VERTICAL)
        root_sizer.Add(self._panel, 1, wx.EXPAND)
        self.SetSizer(root_sizer)
        self.SetSize((900, 600))
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _news_device_entries(self) -> list[tuple[str | None, str]]:
        return news_device_entries(self, placeholder_label=_("(Select playback device)"))

    def _resolve_device(self, requested: str | None) -> str | None:
        if requested:
            return requested
        configured = self._model.get_configured_slots()
        if configured:
            return configured[0] or None
        devices = self._audio_engine.get_devices()
        return devices[0].id if devices else None

    def _on_device_changed(self, model: PlaylistModel) -> None:
        self._editor_settings.set_last_device_id(model.output_device or None)

    def _on_line_length_change(self, value: int) -> None:
        self._line_length = value
        self._editor_settings.set_line_length(value)
        self._persist_editor_preferences()

    def _persist_editor_preferences(self) -> None:
        self._editor_settings.set_line_length(self._line_length)
        device_id = self._panel.get_selected_device_id() or self._model.output_device
        self._editor_settings.set_last_device_id(device_id or None)

    def _on_play_audio(self, path: Path, device_id: str | None) -> None:
        if not path.exists():
            wx.MessageBox(_("Audio file %s does not exist") % path, _("Error"), parent=self)
            return
        target_device = self._resolve_device(device_id)
        if not target_device:
            wx.MessageBox(_("Select a playback device first"), _("Error"), parent=self)
            return
        known_devices = {device.id for device in self._audio_engine.get_devices()}
        if target_device not in known_devices:
            self._audio_engine.refresh_devices()
            known_devices = {device.id for device in self._audio_engine.get_devices()}
        if target_device not in known_devices:
            wx.MessageBox(_("Device %s is not available") % target_device, _("Error"), parent=self)
            return
        try:
            player = self._audio_engine.create_player(target_device)
        except Exception as exc:  # pylint: disable=broad-except
            wx.MessageBox(_("Unable to open device: %s") % exc, _("Error"), parent=self)
            return
        try:
            player.play("news-editor", str(path))
        except Exception as exc:  # pylint: disable=broad-except
            wx.MessageBox(_("Failed to play clip: %s") % exc, _("Error"), parent=self)

    def _on_close(self, event: wx.CloseEvent) -> None:
        try:
            self._audio_engine.stop_all()
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            self._preview_controller.stop_preview()
        except Exception:  # pylint: disable=broad-except
            pass
        event.Skip()
    def _preview_announce(self, _category: str, message: str) -> None:
        wx.MessageBox(message, _("Preview"), parent=self)

    def _preview_news_clip(self, path: Path) -> bool:
        return preview_news_clip(
            self,
            path,
            start_preview=self._preview_controller.start_preview,
            on_missing=lambda missing: wx.MessageBox(
                _("Audio file %s does not exist") % missing,
                _("Error"),
                parent=self,
            ),
            item_id_prefix="news-editor-preview",
        )


def run() -> None:
    """Launch the standalone news editor."""

    app = wx.App()
    settings = SettingsManager()
    set_language(settings.get_language())
    frame = NewsEditorFrame(settings=settings)
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    run()
