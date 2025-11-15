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
from sara.news_editor_settings import NewsEditorSettings


class NewsEditorFrame(wx.Frame):
    """Minimal frame hosting the news playlist panel."""

    def __init__(self, settings: SettingsManager) -> None:
        super().__init__(None, title=_("SARA News Editor"))
        self._settings = settings
        self._audio_engine = AudioEngine()
        self._editor_settings = NewsEditorSettings()
        self._model = PlaylistModel(id="news-editor", name=_("News service"), kind=PlaylistKind.NEWS)
        last_device = self._editor_settings.get_last_device_id()
        if last_device:
            self._model.output_device = last_device
        self._panel = NewsPlaylistPanel(
            self,
            model=self._model,
            get_line_length=self._settings.get_news_line_length,
            get_audio_devices=self._news_device_entries,
            on_focus=lambda _playlist_id: None,
            on_play_audio=self._on_play_audio,
            on_device_change=self._on_device_changed,
        )
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._panel, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self.SetSize((900, 600))
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _news_device_entries(self) -> list[tuple[str | None, str]]:
        devices = self._audio_engine.get_devices()
        entries: list[tuple[str | None, str]] = [(None, _("(Select playback device)"))]
        entries.extend((device.id, device.name) for device in devices)
        return entries

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
        event.Skip()


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
