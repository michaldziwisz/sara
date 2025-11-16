from pathlib import Path

from sara.core.media_metadata import (
    extract_metadata,
    is_supported_audio_file,
    save_mix_metadata,
)


def test_supported_audio_extensions_case_insensitive() -> None:
    assert is_supported_audio_file(Path("song.MP3"))
    assert is_supported_audio_file(Path("/tmp/audio.FlAc"))
    assert is_supported_audio_file(Path("clip.mp4"))


def test_unsupported_extensions_and_sidecar_files() -> None:
    assert not is_supported_audio_file(Path("notes.txt"))
    assert not is_supported_audio_file(Path("track.mp3.reapeaks"))


def test_save_and_extract_mix_metadata(tmp_path) -> None:
    target = tmp_path / "mix.flac"
    target.write_bytes(b"\x00")

    assert save_mix_metadata(
        target,
        cue_in=1.5,
        intro=12.0,
        outro=85.5,
        segue=22.25,
        overlap=3.5,
    )

    metadata = extract_metadata(target)
    assert metadata.cue_in_seconds == 1.5
    assert metadata.intro_seconds == 12.0
    assert metadata.outro_seconds == 85.5
    assert metadata.segue_seconds == 22.25
    assert metadata.overlap_seconds == 3.5


def test_mix_metadata_removal(tmp_path) -> None:
    target = tmp_path / "clean.mp3"
    target.write_bytes(b"\x00")
    save_mix_metadata(
        target,
        cue_in=0.5,
        intro=5.0,
        outro=40.0,
        segue=15.0,
        overlap=2.0,
    )
    assert save_mix_metadata(
        target,
        cue_in=None,
        intro=None,
        outro=None,
        segue=None,
        overlap=None,
    )
    metadata = extract_metadata(target)
    assert metadata.cue_in_seconds is None
    assert metadata.intro_seconds is None
    assert metadata.outro_seconds is None
    assert metadata.segue_seconds is None
    assert metadata.overlap_seconds is None
