"""Helpers for invoking bs1770gain loudness analyzer."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from sara.audio.transcoding import TRANSCODE_EXTENSIONS, transcode_source_to_wav
except Exception:  # pragma: no cover - audio layer optional in some environments
    TRANSCODE_EXTENSIONS = set()
    transcode_source_to_wav = None  # type: ignore[assignment]


class LoudnessStandard(Enum):
    """Normalization references."""

    EBU = "ebu"  # -23 LUFS
    ATSC = "atsc"  # -24 LUFS


@dataclass
class LoudnessMeasurement:
    integrated_lufs: float


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []
    path = shutil.which("bs1770gain")
    if path:
        candidates.append(Path(path))
    base = Path(__file__).resolve().parents[1]  # .../src/sara
    vendor_root = base / "audio" / "vendor" / "windows" / "bs1770gain"
    for name in ("bs1770gain", "bs1770gain.exe"):
        candidate = vendor_root / name
        if candidate not in candidates:
            candidates.append(candidate)
    if hasattr(sys, "frozen"):
        executable = Path(getattr(sys, "executable", sys.argv[0] or ""))
        for name in ("bs1770gain", "bs1770gain.exe"):
            candidate = executable.parent / name
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def find_bs1770gain() -> Path | None:
    for candidate in _candidate_paths():
        if candidate and candidate.exists():
            return candidate
    return None


def analyze_loudness(path: Path, *, standard: LoudnessStandard) -> LoudnessMeasurement:
    executable = find_bs1770gain()
    if executable is None:
        raise FileNotFoundError("bs1770gain was not found on PATH or bundled resources")

    def _run_for(target: Path) -> LoudnessMeasurement:
        completed = _run_bs1770gain(executable, target, standard)
        used_temp_copy = False
        if completed.returncode != 0:
            fallback = _retry_with_temp_copy(executable, target, standard)
            if fallback is not None:
                completed = fallback
                used_temp_copy = True
        if completed.returncode != 0:
            stderr_text = (getattr(completed, "stderr", None) or "").strip()
            stdout_text = (getattr(completed, "stdout", None) or "").strip()
            raise RuntimeError(stderr_text or stdout_text or "bs1770gain failed")

        try:
            xml_text = _extract_xml(getattr(completed, "stdout", None), getattr(completed, "stderr", None))
            root = ET.fromstring(xml_text)
        except RuntimeError as exc:
            if "missing XML payload" in str(exc) and not used_temp_copy:
                fallback = _retry_with_temp_copy(executable, target, standard)
                if fallback is not None:
                    completed = fallback
                    xml_text = _extract_xml(getattr(completed, "stdout", None), getattr(completed, "stderr", None))
                    root = ET.fromstring(xml_text)
                else:
                    raise
            else:
                raise
        except ET.ParseError as exc:  # pragma: no cover - depends on CLI output
            raise RuntimeError(f"Unable to parse bs1770gain output: {exc}") from exc

        track_node = root.find("./track/integrated")
        if track_node is None or "lufs" not in track_node.attrib:
            raise RuntimeError("bs1770gain output did not include integrated loudness")
        integrated = float(track_node.attrib["lufs"])
        return LoudnessMeasurement(integrated_lufs=integrated)

    try:
        return _run_for(path)
    except RuntimeError as exc:
        if transcode_source_to_wav is None:
            raise
        if not executable.exists():
            raise
        if path.suffix.lower() not in TRANSCODE_EXTENSIONS:
            raise

        try:
            wav_path = transcode_source_to_wav(path)
        except Exception:
            raise exc from None
        try:
            return _run_for(wav_path)
        finally:
            try:
                wav_path.unlink(missing_ok=True)
            except Exception:
                pass


def _extract_xml(output: str | None, stderr: str | None = None) -> str:
    output_text = output or ""
    stderr_text = stderr or ""
    candidate = output_text if output_text.strip() else stderr_text
    candidate = candidate.replace("\b", "")
    candidate = "".join(ch for ch in candidate if ch.isprintable() or ch in "\n\r\t<>/\"'=.-: ")
    candidate = re.sub(r"&(?!#?\w+;)", "&amp;", candidate)
    start = candidate.find("<bs1770gain")
    if start == -1:
        raise RuntimeError(
            "bs1770gain output missing XML payload. "
            f"stdout={_summarize_output(output_text)} stderr={_summarize_output(stderr_text)}"
        )
    candidate = candidate[start:]
    end = candidate.find("</bs1770gain>")
    if end == -1:
        raise RuntimeError(
            "bs1770gain output missing XML payload. "
            f"stdout={_summarize_output(output_text)} stderr={_summarize_output(stderr_text)}"
        )
    end += len("</bs1770gain>")
    return candidate[:end]


def _summarize_output(text: str, *, limit: int = 240) -> str:
    cleaned = text.replace("\r", "\\r").replace("\n", "\\n")
    cleaned = cleaned.strip()
    if not cleaned:
        return "<empty>"
    if len(cleaned) <= limit:
        return repr(cleaned)
    return repr(cleaned[:limit] + "…")


def _run_bs1770gain(executable: Path, target: Path, standard: LoudnessStandard) -> subprocess.CompletedProcess[str]:
    cmd = [str(executable), "--xml"]
    if standard is LoudnessStandard.ATSC:
        cmd.append("--atsc")
    else:
        cmd.append("--ebu")
    cmd.append(str(target))

    logger.debug("Running bs1770gain: %s", cmd)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )


def _retry_with_temp_copy(
    executable: Path,
    original_path: Path,
    standard: LoudnessStandard,
) -> subprocess.CompletedProcess[str] | None:
    """Attempt bs1770gain again using an ASCII-only temporary copy."""

    suffix = original_path.suffix or ""
    try:
        with tempfile.TemporaryDirectory(prefix="sara_bs1770gain_") as temp_dir:
            safe_path = Path(temp_dir) / f"sara_loudness{suffix}"
            shutil.copy2(original_path, safe_path)
            logger.debug("Retrying bs1770gain using temporary copy %s", safe_path)
            return _run_bs1770gain(executable, safe_path, standard)
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Failed to run bs1770gain via temporary copy: %s", exc)
        return None
