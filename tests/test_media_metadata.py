from pathlib import Path

from sara.core.media_metadata import is_supported_audio_file


def test_supported_audio_extensions_case_insensitive() -> None:
    assert is_supported_audio_file(Path("song.MP3"))
    assert is_supported_audio_file(Path("/tmp/audio.FlAc"))


def test_unsupported_extensions_and_sidecar_files() -> None:
    assert not is_supported_audio_file(Path("notes.txt"))
    assert not is_supported_audio_file(Path("track.mp3.reapeaks"))
