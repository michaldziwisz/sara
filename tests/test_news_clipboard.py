from __future__ import annotations

import sys
import types

if "wx" not in sys.modules:
    sys.modules["wx"] = types.SimpleNamespace()

# Stub media_metadata to avoid heavy deps during unit test runs without full env.
media_module = types.ModuleType("sara.core.media_metadata")
media_module.is_supported_audio_file = lambda _p: True  # type: ignore[attr-defined]
sys.modules.setdefault("sara.core", types.ModuleType("sara.core"))
sys.modules["sara.core.media_metadata"] = media_module

import sara.news.clipboard as clip


def test_clipboard_audio_paths_handles_win32_failure(monkeypatch):
    monkeypatch.setattr(clip, "_collect_clipboard_strings", lambda: ["dummy.mp3"])
    monkeypatch.setattr(clip, "_collect_from_path", lambda _raw, bucket: bucket.append("ok.mp3"))
    monkeypatch.setattr(clip, "_collect_win32_file_drops", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    assert clip.clipboard_audio_paths() == ["ok.mp3"]
