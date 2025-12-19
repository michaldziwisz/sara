from __future__ import annotations

from sara.audio.bass._manager.text import decode_bass_text


def test_decode_bass_text_preserves_polish_chars_from_cp1250() -> None:
    original = "Urządzenie Łódź"
    raw = original.encode("cp1250")
    assert decode_bass_text(raw) == original


def test_decode_bass_text_handles_utf8() -> None:
    original = "Urządzenie Łódź"
    raw = original.encode("utf-8")
    assert decode_bass_text(raw) == original

