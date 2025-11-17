"""Helpers for invoking bs1770gain loudness analyzer."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
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

    cmd = [str(executable), "--xml"]
    if standard is LoudnessStandard.ATSC:
        cmd.append("--atsc")
    else:
        cmd.append("--ebu")
    cmd.append(str(path))

    logger.debug("Running bs1770gain: %s", cmd)
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
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
    start = candidate.find("<bs1770gain")
    if start == -1:
        raise RuntimeError("bs1770gain output missing XML payload")
    candidate = candidate[start:]
    end = candidate.find("</bs1770gain>")
    if end == -1:
        raise RuntimeError("bs1770gain output missing XML payload")
    end += len("</bs1770gain>")
    return candidate[:end]
