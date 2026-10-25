from pathlib import Path

from pytest import approx

from sara.core.media_metadata import (
    extract_metadata,
    is_supported_audio_file,
    save_mix_metadata,
    save_replay_gain_metadata,
)


def test_supported_audio_extensions_case_insensitive() -> None:
    assert is_supported_audio_file(Path("song.MP3"))
    assert is_supported_audio_file(Path("/tmp/audio.FlAc"))
    assert is_supported_audio_file(Path("clip.mp4"))
    assert is_supported_audio_file(Path("jingle.mp2"))
    assert is_supported_audio_file(Path("spot.MPEG"))
    assert is_supported_audio_file(Path("spot.MpG"))


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
        segue_fade=0.5,
        overlap=3.5,
    )

    metadata = extract_metadata(target)
    assert metadata.cue_in_seconds == 1.5
    assert metadata.intro_seconds == 12.0
    assert metadata.outro_seconds == 85.5
    assert metadata.segue_seconds == 22.25
    assert metadata.segue_fade_seconds == 0.5
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
        segue_fade=1.5,
        overlap=2.0,
    )
    assert save_mix_metadata(
        target,
        cue_in=None,
        intro=None,
        outro=None,
        segue=None,
        segue_fade=None,
        overlap=None,
    )
    metadata = extract_metadata(target)
    assert metadata.cue_in_seconds is None
    assert metadata.intro_seconds is None
    assert metadata.outro_seconds is None
    assert metadata.segue_seconds is None
    assert metadata.segue_fade_seconds is None
    assert metadata.overlap_seconds is None


def test_save_replay_gain_metadata(tmp_path) -> None:
    target = tmp_path / "gain.wav"
    target.write_bytes(b"\x00")
    assert save_replay_gain_metadata(target, 4.25)
    metadata = extract_metadata(target)
    assert metadata.replay_gain_db == approx(4.25, abs=1e-3)


def test_clear_replay_gain_metadata(tmp_path) -> None:
    target = tmp_path / "gain_clear.wav"
    target.write_bytes(b"\x00")
    save_replay_gain_metadata(target, -3.0)
    assert save_replay_gain_metadata(target, None)
    metadata = extract_metadata(target)
    assert metadata.replay_gain_db is None


def test_spl_unset_mix_points_are_none(tmp_path) -> None:
    # StationPlaylist zapisuje nieustawiony punkt jako -1 (np. Intro=-1, Outro=-1).
    from mutagen.apev2 import APEv2

    target = tmp_path / "spl.mp3"
    target.write_bytes(b"\x00")
    tags = APEv2()
    for key, value in {"Intro": "-1", "Outro": "-1", "Cue": "2900", "Segue": "190500",
                       "CueOverlap": "0", "FadeOut": "-1"}.items():
        tags[key] = value
    tags.save(target)

    metadata = extract_metadata(target)
    assert metadata.intro_seconds is None
    assert metadata.outro_seconds is None
    assert metadata.cue_in_seconds == approx(2.9)
    assert metadata.segue_seconds == approx(187.6)  # Segue SPL 190,5 s od początku pliku minus Cue 2,9 s
    assert metadata.overlap_seconds == 0.0


def test_spl_segue_is_absolute_and_sara_segue_is_relative(tmp_path) -> None:
    # Loona - Rhythm Of The Night: Cue 3200, Segue 222600, CueOut 222980 (ms od początku pliku).
    from mutagen.apev2 import APEv2

    spl = tmp_path / "spl.mp3"
    spl.write_bytes(b"\x00")
    tags = APEv2()
    for key, value in {"Cue": "3200", "Segue": "222600", "CueOut": "222980", "SegueDB": "1"}.items():
        tags[key] = value
    tags.save(spl)
    metadata = extract_metadata(spl)
    assert metadata.cue_in_seconds == approx(3.2)
    assert metadata.segue_seconds == approx(219.4)  # 3,2 + 219,4 = 222,6 jak w StationPlaylist

    own = tmp_path / "sara.flac"
    own.write_bytes(b"\x00")
    assert save_mix_metadata(own, cue_in=3.2, intro=None, outro=None, segue=219.4, segue_fade=None, overlap=None)
    assert extract_metadata(own).segue_seconds == approx(219.4)


def test_spl_segue_before_cue_clamps_to_cue(tmp_path) -> None:
    from mutagen.apev2 import APEv2

    spl = tmp_path / "early.mp3"
    spl.write_bytes(b"\x00")
    tags = APEv2()
    tags["Cue"] = "5000"
    tags["Segue"] = "4000"
    tags.save(spl)
    assert extract_metadata(spl).segue_seconds == 0.0
