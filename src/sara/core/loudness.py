"""Helpers for invoking bs1770gain loudness analyzer."""

from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextvars import ContextVar
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from sara.audio.transcoding import TRANSCODE_EXTENSIONS
except Exception:  # pragma: no cover - audio layer optional in some environments
    TRANSCODE_EXTENSIONS = set()


class LoudnessStandard(Enum):
    """Normalization references."""

    EBU = "ebu"  # -23 LUFS
    ATSC = "atsc"  # -24 LUFS


@dataclass
class LoudnessMeasurement:
    integrated_lufs: float
    true_peak_dbtp: float | None = None


@dataclass(frozen=True)
class NormalizationResult:
    gain_db: float
    measured_lufs: float
    marker: str


def normalization_result(measurement: LoudnessMeasurement, *, standard: LoudnessStandard) -> NormalizationResult:
    """Wspólne wzmocnienie dla automatu i PFL, z zapasem true peak."""
    integrated = measurement.integrated_lufs
    peak = measurement.true_peak_dbtp
    if peak is None or not math.isfinite(integrated) or not math.isfinite(peak):
        raise ValueError("Loudness normalization requires finite integrated and true peak measurements")
    target = -23.0 if standard is LoudnessStandard.EBU else -24.0
    gain = min(target - integrated, -1.0 - peak)  # LOUDNESS_TRUE_PEAK
    gain = max(-60.0, min(18.0, gain))
    # Tag ReplayGain ma dwa miejsca po przecinku: nie zaokrąglamy w górę ponad limit TP.
    gain = math.floor(round(gain * 100, 6)) / 100
    label = "EBU R128" if standard is LoudnessStandard.EBU else "ATSC A/85"
    marker = f"{label};I={integrated:.2f};TP={peak:.2f};target={target:g};gain={gain:+.2f}"
    return NormalizationResult(gain, integrated, marker)


def measure_normalization(path: Path, *, standard: LoudnessStandard) -> NormalizationResult:
    return normalization_result(analyze_loudness(path, standard=standard), standard=standard)


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


_deadline: ContextVar[float | None] = ContextVar("loudness_deadline", default=None)


def analyze_loudness(path: Path, *, standard: LoudnessStandard) -> LoudnessMeasurement:
    token = _deadline.set(time.monotonic() + 120.0)
    try:
        return _analyze_loudness(path, standard=standard)
    finally:
        _deadline.reset(token)


def _analyze_loudness(path: Path, *, standard: LoudnessStandard) -> LoudnessMeasurement:
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

        stderr_text = getattr(completed, "stderr", None) or ""
        if completed.returncode != 0 or re.search(r"(?i)\berror:", stderr_text):
            # Niektóre wydania zwracają kod 0 i XML także po błędzie dekodera.
            raise RuntimeError(stderr_text.strip() or "bs1770gain failed")
        track_node = root.find("./track/integrated")
        if track_node is None or "lufs" not in track_node.attrib:
            raise RuntimeError("bs1770gain output did not include integrated loudness")
        integrated = float(track_node.attrib["lufs"])
        peak_node = root.find("./track/true-peak")
        peak = float(peak_node.attrib["tpfs"]) if peak_node is not None and "tpfs" in peak_node.attrib else None
        if not math.isfinite(integrated) or (peak is not None and not math.isfinite(peak)):
            raise RuntimeError("bs1770gain returned non-finite loudness")
        return LoudnessMeasurement(integrated_lufs=integrated, true_peak_dbtp=peak)

    try:
        return _run_for(path)
    except RuntimeError as exc:
        if not executable.exists():
            raise
        if path.suffix.lower() not in TRANSCODE_EXTENSIONS:
            raise

        try:
            wav_path = _transcode_for_analysis(path)
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
    cmd = [str(executable), "--xml", "-i", "-t"]
    if standard is LoudnessStandard.ATSC:
        cmd.append("--atsc")
    else:
        cmd.append("--ebu")
    cmd.append(str(target))

    logger.debug("Running bs1770gain: %s", cmd)
    return _run_analysis_command(cmd)


def _run_analysis_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    deadline = _deadline.get()
    timeout = max(0.0, deadline - time.monotonic()) if deadline is not None else 120.0
    if timeout <= 0:
        raise subprocess.TimeoutExpired(cmd, 120)
    return subprocess.run(
        cmd, capture_output=True, text=True, check=False, timeout=timeout,
        creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if sys.platform == "win32" else 0,
    )


def _transcode_for_analysis(source: Path) -> Path:
    # Fallback odtwarzania nie ma limitu czasu ani flag procesu Windows.
    # Analiza korzysta z tego samego budżetu i launchera co bs1770gain.
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("FFmpeg is required for loudness analysis fallback")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temporary:
        target = Path(temporary.name)
    try:
        completed = _run_analysis_command([
            executable, "-nostdin", "-y", "-i", str(source), "-vn",
            "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "2", str(target),
        ])
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or "FFmpeg failed")
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


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
    except subprocess.TimeoutExpired:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Failed to run bs1770gain via temporary copy: %s", exc)
        return None
