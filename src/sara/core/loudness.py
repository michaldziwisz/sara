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

    completed = _run_bs1770gain(executable, path, standard)
    if completed.returncode != 0:
        fallback = _retry_with_temp_copy(executable, path, standard)
        if fallback is not None:
            completed = fallback
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "bs1770gain failed")

    xml_text = _extract_xml(completed.stdout, completed.stderr)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:  # pragma: no cover - depends on CLI output
        raise RuntimeError(f"Unable to parse bs1770gain output: {exc}") from exc

    track_node = root.find("./track/integrated")
    if track_node is None or "lufs" not in track_node.attrib:
        raise RuntimeError("bs1770gain output did not include integrated loudness")
    integrated = float(track_node.attrib["lufs"])
    return LoudnessMeasurement(integrated_lufs=integrated)


def _extract_xml(output: str, stderr: str | None = None) -> str:
    candidate = output if output.strip() else (stderr or "")
    candidate = candidate.replace("\b", "")
    candidate = "".join(ch for ch in candidate if ch.isprintable() or ch in "\n\r\t<>/\"'=.-: ")
    candidate = re.sub(r"&(?!#?\w+;)", "&amp;", candidate)
    start = candidate.find("<bs1770gain")
    if start == -1:
        raise RuntimeError("bs1770gain output missing XML payload")
    candidate = candidate[start:]
    end = candidate.find("</bs1770gain>")
    if end == -1:
        raise RuntimeError("bs1770gain output missing XML payload")
    end += len("</bs1770gain>")
    return candidate[:end]


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
