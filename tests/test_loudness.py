from pathlib import Path
from types import SimpleNamespace

import pytest
import xml.etree.ElementTree as ET

from sara.core import loudness as loudness_module
from sara.core.loudness import LoudnessStandard, analyze_loudness, find_bs1770gain, _extract_xml


@pytest.mark.skipif(find_bs1770gain() is None, reason="bs1770gain not available")
def test_analyze_loudness_returns_value() -> None:
    measurement = analyze_loudness(Path("src/sara/audio/media/beep.wav"), standard=LoudnessStandard.EBU)
    assert isinstance(measurement.integrated_lufs, float)


def test_analyze_loudness_retries_with_temp_copy(tmp_path, monkeypatch) -> None:
    """Ensure we fall back to a safe temporary copy when bs1770gain fails."""

    track_path = tmp_path / "zażółć gęślą-ś.mp3"
    track_path.write_bytes(b"not-audio")

    calls: list[Path] = []
    outputs = [
        SimpleNamespace(returncode=1, stdout="", stderr="boom"),
        SimpleNamespace(
            returncode=0,
            stdout='<bs1770gain><track><integrated lufs="-18.50"/></track></bs1770gain>',
            stderr="",
        ),
    ]

    def fake_run(executable: Path, target: Path, standard: LoudnessStandard):
        del executable, standard  # unused in fake
        calls.append(Path(target))
        return outputs.pop(0)

    monkeypatch.setattr(loudness_module, "find_bs1770gain", lambda: Path("dummy-bs.exe"))
    monkeypatch.setattr(loudness_module, "_run_bs1770gain", fake_run)

    measurement = analyze_loudness(track_path, standard=LoudnessStandard.EBU)

    assert measurement.integrated_lufs == pytest.approx(-18.5)
    assert len(calls) == 2
    assert calls[0] == track_path
    assert calls[1] != track_path
    assert "sara_loudness" in calls[1].name


def test_extract_xml_sanitizes_ampersand_and_controls() -> None:
    xml_blob = (
        "noise\x08noise"
        '<bs1770gain version="0.1">\n'
        '<track path="Yugopolis & Maciej Malenczuk - Ostatnia Nocka">'
        '<integrated lufs="-18.50"/></track></bs1770gain>'
    )
    cleaned = _extract_xml(xml_blob, None)
    root = ET.fromstring(cleaned)
    track = root.find("./track")
    assert track is not None
    assert track.attrib["path"].endswith("Yugopolis & Maciej Malenczuk - Ostatnia Nocka")


def test_analyze_loudness_handles_missing_process_output(monkeypatch, tmp_path) -> None:
    """Regression: some subprocess wrappers may return stdout/stderr as None."""

    track_path = tmp_path / "broken.mp3"
    track_path.write_bytes(b"not-audio")

    def fake_run(_executable: Path, _target: Path, _standard: LoudnessStandard):
        return SimpleNamespace(returncode=1, stdout=None, stderr=None)

    monkeypatch.setattr(loudness_module, "find_bs1770gain", lambda: Path("dummy-bs.exe"))
    monkeypatch.setattr(loudness_module, "_run_bs1770gain", fake_run)
    monkeypatch.setattr(loudness_module, "_retry_with_temp_copy", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="bs1770gain failed"):
        analyze_loudness(track_path, standard=LoudnessStandard.EBU)


def test_analyze_loudness_retries_when_xml_missing(monkeypatch, tmp_path) -> None:
    track_path = tmp_path / "unicodę.mp3"
    track_path.write_bytes(b"not-audio")

    outputs = [
        SimpleNamespace(returncode=0, stdout="Can't open file", stderr=""),
        SimpleNamespace(
            returncode=0,
            stdout='<bs1770gain><track><integrated lufs="-20.00"/></track></bs1770gain>',
            stderr="",
        ),
    ]

    def fake_run(_executable: Path, _target: Path, _standard: LoudnessStandard):
        return outputs.pop(0)

    monkeypatch.setattr(loudness_module, "find_bs1770gain", lambda: Path("dummy-bs.exe"))
    monkeypatch.setattr(loudness_module, "_run_bs1770gain", fake_run)

    measurement = analyze_loudness(track_path, standard=LoudnessStandard.EBU)
    assert measurement.integrated_lufs == pytest.approx(-20.0)
