from __future__ import annotations

import sys
import types
from pathlib import Path

if "wx" not in sys.modules:
    sys.modules["wx"] = types.SimpleNamespace(CallAfter=lambda fn, *args, **kwargs: fn(*args, **kwargs))

from sara.core.playlist import PlaylistItem
from sara.ui.controllers.playback import alerts as alerts_mod
from sara.ui.playback import preview as preview_mod


class _FakePlayer:
    def __init__(self, *, active: bool = False) -> None:
        self._active = active
        self.finished_callback = None
        self.progress_callback = None
        self.play_calls: list[tuple[str, str]] = []
        self.loop_calls: list[tuple[float | None, float | None]] = []
        self.events: list[str] = []

    def is_active(self) -> bool:
        return self._active

    def set_finished_callback(self, callback) -> None:  # noqa: ANN001 - compat shim
        self.finished_callback = callback

    def set_progress_callback(self, callback) -> None:  # noqa: ANN001 - compat shim
        self.progress_callback = callback

    def set_gain_db(self, _gain_db) -> None:  # noqa: ANN001 - compat shim
        return

    def play(self, playlist_item_id: str, source_path: str, *, start_seconds: float = 0.0, allow_loop: bool = True):  # noqa: ANN001, E501 - compat shim
        _ = start_seconds, allow_loop
        self.events.append("play")
        self.play_calls.append((playlist_item_id, source_path))
        return None

    def set_loop(self, start_seconds, end_seconds) -> None:  # noqa: ANN001 - compat shim
        self.events.append("set_loop")
        self.loop_calls.append((start_seconds, end_seconds))

    def stop(self) -> None:
        self._active = False


def test_is_preview_active_checks_player_state() -> None:
    inactive_context = types.SimpleNamespace(players=[_FakePlayer(active=False)])
    active_context = types.SimpleNamespace(players=[_FakePlayer(active=True)])

    frame_inactive = types.SimpleNamespace(_playback=types.SimpleNamespace(preview_context=inactive_context))
    frame_active = types.SimpleNamespace(_playback=types.SimpleNamespace(preview_context=active_context))

    assert alerts_mod._is_preview_active(frame_inactive) is False
    assert alerts_mod._is_preview_active(frame_active) is True


def test_start_preview_clears_context_when_finished(tmp_path: Path) -> None:
    class _Settings:
        def get_pfl_device(self) -> str:
            return "pfl:1"

    class _AudioEngine:
        def __init__(self) -> None:
            self.player = _FakePlayer(active=True)

        def get_devices(self):  # noqa: ANN001 - test stub
            return [types.SimpleNamespace(id="pfl:1")]

        def refresh_devices(self) -> None:
            return

        def create_player(self, _device_id: str) -> _FakePlayer:
            return self.player

        def create_player_instance(self, _device_id: str) -> _FakePlayer:
            return self.player

    class _Controller:
        def __init__(self) -> None:
            self._audio_engine = _AudioEngine()
            self._settings = _Settings()
            self._pfl_device_id = "pfl:1"
            self._preview_context = None
            self.announcements: list[tuple[str, str]] = []

        def _announce(self, category: str, message: str) -> None:
            self.announcements.append((category, message))

        def get_busy_device_ids(self) -> set[str]:
            return set()

    controller = _Controller()
    item_path = tmp_path / "clip.wav"
    item_path.write_bytes(b"data")
    item = PlaylistItem(id="it-1", path=item_path, title="Clip", duration_seconds=10.0)

    assert preview_mod.start_preview(controller, item, 0.0) is True
    assert controller._preview_context is not None
    assert controller._audio_engine.player.finished_callback is not None

    controller._audio_engine.player.finished_callback("it-1:preview")
    assert controller._preview_context is None


def test_start_preview_sets_loop_before_play(tmp_path: Path) -> None:
    class _Settings:
        def get_pfl_device(self) -> str:
            return "pfl:1"

    class _AudioEngine:
        def __init__(self) -> None:
            self.player = _FakePlayer(active=True)

        def get_devices(self):  # noqa: ANN001 - test stub
            return [types.SimpleNamespace(id="pfl:1")]

        def refresh_devices(self) -> None:
            return

        def create_player_instance(self, _device_id: str) -> _FakePlayer:
            return self.player

    controller = types.SimpleNamespace(
        _audio_engine=_AudioEngine(),
        _settings=_Settings(),
        _pfl_device_id="pfl:1",
        _preview_context=None,
        _announce=lambda *_args, **_kwargs: None,
        get_busy_device_ids=lambda: set(),
    )
    item_path = tmp_path / "clip.wav"
    item_path.write_bytes(b"data")
    item = PlaylistItem(id="it-1", path=item_path, title="Clip", duration_seconds=10.0)

    assert preview_mod.start_preview(controller, item, 2.0, loop_range=(2.0, 4.0)) is True

    player = controller._audio_engine.player
    assert player.loop_calls[0] == (2.0, 4.0)
    assert player.events[:2] == ["set_loop", "play"]


def test_update_loop_preview_updates_first_preview_player(tmp_path: Path) -> None:
    player = _FakePlayer(active=True)
    item_path = tmp_path / "clip.wav"
    item_path.write_bytes(b"data")
    item = PlaylistItem(id="it-1", path=item_path, title="Clip", duration_seconds=10.0)
    controller = types.SimpleNamespace(
        _preview_context=preview_mod.PreviewContext(players=[player], device_id="pfl:1", item_path=item_path),
        _announce=lambda *_args, **_kwargs: None,
    )

    assert preview_mod.update_loop_preview(controller, item, 1.5, 3.5) is True
    assert player.loop_calls == [(1.5, 3.5)]
