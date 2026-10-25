from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from sara.core import loudness
from sara.core.media_metadata import save_replay_gain_metadata, extract_metadata
from sara.ui.dialogs.mix_point import loudness as dialog_loudness


@pytest.mark.parametrize('integrated,peak,expected', [(-30, -2, 1), (-14, -1.3, -9), (-14.13, -1.3, -8.87), (-100, -100, 18), (40, 0, -60)])
def test_gain_is_true_peak_limited(integrated, peak, expected, monkeypatch):
    measurement = loudness.LoudnessMeasurement(integrated_lufs=integrated, true_peak_dbtp=peak)
    result = loudness.normalization_result(measurement, standard=loudness.LoudnessStandard.EBU)
    assert result.gain_db == expected
    monkeypatch.setattr(dialog_loudness, 'analyze_loudness', lambda *a, **k: measurement)
    gain, measured = dialog_loudness.compute_normalization_gain(Path('track.mp3'), standard=loudness.LoudnessStandard.EBU)
    assert gain == result.gain_db
    assert measured == integrated


def test_xml_and_subprocess_options(monkeypatch):
    calls = []
    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout='noise\b<bs1770gain><track><integrated lufs="-14.13"/><true-peak tpfs="-1.30"/></track></bs1770gain>', stderr='')
    monkeypatch.setattr(loudness, 'find_bs1770gain', lambda: Path('bs1770gain'))
    monkeypatch.setattr(loudness.subprocess, 'run', run)
    monkeypatch.setattr(loudness.sys, 'platform', 'win32')
    monkeypatch.setattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0x00004000, raising=False)
    result = loudness.analyze_loudness(Path('track.mp3'), standard=loudness.LoudnessStandard.EBU)
    assert result.integrated_lufs == -14.13
    assert result.true_peak_dbtp == -1.3
    cmd, options = calls[0]
    assert '-i' in cmd and '-t' in cmd and '--ebu' in cmd
    assert 0 < options['timeout'] <= 120
    assert options['creationflags'] == 0x08004000


@pytest.mark.parametrize('integrated,peak', [('nan', '-2'), ('-inf', '-inf'), ('-20', 'nan')])
def test_nonfinite_measurement_rejected(monkeypatch, integrated, peak):
    monkeypatch.setattr(loudness, 'find_bs1770gain', lambda: Path('bs1770gain'))
    monkeypatch.setattr(loudness.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stderr='', stdout=f'<bs1770gain><track><integrated lufs="{integrated}"/><true-peak tpfs="{peak}"/></track></bs1770gain>'))
    with pytest.raises(RuntimeError):
        loudness.analyze_loudness(Path('track.mp3'), standard=loudness.LoudnessStandard.EBU)


def test_failed_retry_cannot_return_successful_measurement(monkeypatch, tmp_path):
    path = tmp_path / 'tone.wav'
    path.write_bytes(b'fixture')
    outputs = iter([
        SimpleNamespace(returncode=0, stdout='no XML', stderr=''),
        SimpleNamespace(returncode=1, stderr='decoder failed', stdout='<bs1770gain><track><integrated lufs="-30"/><true-peak tpfs="-2"/></track></bs1770gain>'),
    ])
    monkeypatch.setattr(loudness, 'find_bs1770gain', lambda: Path('missing-bs1770gain'))
    monkeypatch.setattr(loudness.subprocess, 'run', lambda *a, **k: next(outputs))
    with pytest.raises(RuntimeError, match='decoder failed'):
        loudness.analyze_loudness(path, standard=loudness.LoudnessStandard.EBU)


def test_error_exit_zero_is_not_a_valid_measurement(monkeypatch):
    monkeypatch.setattr(loudness, 'find_bs1770gain', lambda: Path('missing-bs1770gain'))
    monkeypatch.setattr(loudness.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='<bs1770gain><track><integrated lufs="-70"/><true-peak tpfs="-12"/></track></bs1770gain>',
        stderr='Error: converting frame: Input changed (ff_resampler.c:179:resampler_apply)'))
    with pytest.raises(RuntimeError, match='converting frame'):
        loudness.analyze_loudness(Path('track.wav'), standard=loudness.LoudnessStandard.EBU)


def test_timeout_is_not_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(loudness, 'find_bs1770gain', lambda: Path('bs1770gain'))
    def timeout(cmd, **kwargs):
        calls.append(cmd)
        raise subprocess.TimeoutExpired(cmd, 120)
    monkeypatch.setattr(loudness.subprocess, 'run', timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        loudness.analyze_loudness(Path('track.mp3'), standard=loudness.LoudnessStandard.EBU)
    assert len(calls) == 1


def test_atsc_target_and_true_peak():
    assert loudness.normalization_result(loudness.LoudnessMeasurement(-14, -1.3),
        standard=loudness.LoudnessStandard.ATSC).gain_db == -10.0
    assert loudness.normalization_result(loudness.LoudnessMeasurement(-30, -2),
        standard=loudness.LoudnessStandard.ATSC).gain_db == 1.0


def test_timeout_budget_includes_temp_copy_and_transcode(monkeypatch, tmp_path):
    executable = tmp_path / 'bs1770gain'
    executable.touch()
    path = tmp_path / 'music.m4a'
    path.write_bytes(b'fixture')
    clock = [0.0]
    timeouts = []
    monkeypatch.setattr(loudness, 'find_bs1770gain', lambda: executable)
    monkeypatch.setattr(loudness.shutil, 'which', lambda *a: 'ffmpeg')
    monkeypatch.setattr(loudness.time, 'monotonic', lambda: clock[0])
    def run(cmd, **kwargs):
        timeouts.append(kwargs['timeout'])
        clock[0] += 30
        if 'ffmpeg' == cmd[0]:
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if len(timeouts) < 4:
            return SimpleNamespace(returncode=1, stdout='', stderr='decoder error')
        return SimpleNamespace(returncode=0, stderr='', stdout='<bs1770gain><track><integrated lufs="-30"/><true-peak tpfs="-2"/></track></bs1770gain>')
    monkeypatch.setattr(loudness.subprocess, 'run', run)
    result = loudness.analyze_loudness(path, standard=loudness.LoudnessStandard.EBU)
    assert result.integrated_lufs == -30
    assert timeouts == [120, 90, 60, 30]


def test_missing_peak_cannot_normalize():
    with pytest.raises(ValueError):
        loudness.normalization_result(loudness.LoudnessMeasurement(-20), standard=loudness.LoudnessStandard.EBU)


@pytest.mark.skipif(loudness.find_bs1770gain() is None, reason='bs1770gain not available')
def test_real_wav_with_true_peak(tmp_path):
    import numpy as np
    import soundfile as sf
    path = tmp_path / 'tone.wav'
    # WAVEX jawnie opisuje kanał, 192 kHz omija wadliwy upsampler
    # bs1770gain 0.8.8 + FFmpeg 6. Zwykły WAV bada test odmowy błędnego XML.
    sf.write(path, .25 * np.sin(2 * np.pi * 1000 * np.arange(192000) / 192000),
             192000, format='WAVEX', subtype='PCM_16')
    result = loudness.analyze_loudness(path, standard=loudness.LoudnessStandard.EBU)
    assert -30 < result.integrated_lufs < -5
    assert -15 < result.true_peak_dbtp < -10
    original_samples, rate = sf.read(path)
    normalized = loudness.normalization_result(result, standard=loudness.LoudnessStandard.EBU)
    assert save_replay_gain_metadata(path, normalized.gain_db, sara_loudness=normalized.marker)
    assert extract_metadata(path).sara_loudness == normalized.marker
    tagged_samples, tagged_rate = sf.read(path)
    assert tagged_rate == rate and np.array_equal(original_samples, tagged_samples)
