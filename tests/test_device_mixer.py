from __future__ import annotations

import time
from threading import Event

import numpy as np

from sara.audio.engine import AudioDevice, BackendType
import sara.audio.mixer.device_mixer as mixer_mod
from sara.audio.mixer import DeviceMixer, NullOutputStream


class FakeSoundFile:
    def __init__(self, data: np.ndarray, samplerate: int = 48000):
        self.data = data.astype("float32")
        if self.data.ndim == 1:
            self.data = self.data[:, None]
        self.samplerate = samplerate
        self.channels = self.data.shape[1]
        self._pos = 0

    def read(self, frames: int, dtype="float32", always_2d=True):
        if self._pos >= len(self.data):
            return np.zeros((0, self.channels), dtype="float32")
        end = min(len(self.data), self._pos + frames)
        chunk = self.data[self._pos : end].astype(dtype)
        self._pos = end
        if always_2d and chunk.ndim == 1:
            chunk = chunk[:, None]
        return chunk

    def seek(self, frame: int):
        self._pos = max(0, min(frame, len(self.data)))

    def __len__(self) -> int:
        return len(self.data)

    def close(self):
        return None


class DummySF:
    def __init__(self, mapping):
        self._mapping = mapping

    def SoundFile(self, path, mode="r"):
        return self._mapping[str(path)]


def test_device_mixer_soft_mix_and_callbacks(monkeypatch, tmp_path):
    data_one = np.linspace(-1.0, 1.0, 96, dtype="float32")
    data_two = np.ones(64, dtype="float32") * 0.25

    files = {
        "one": FakeSoundFile(data_one),
        "two": FakeSoundFile(data_two),
    }

    monkeypatch.setattr(mixer_mod, "sf", DummySF(files))
    monkeypatch.setattr(mixer_mod, "sd", None)

    writes = []
    finished: list[str] = []
    progress: list[tuple[str, float]] = []

    device = AudioDevice(id="dev-1", name="Test", backend=BackendType.WASAPI, raw_index=None)
    mixer = DeviceMixer(device, block_size=32, stream_factory=lambda sr, ch: NullOutputStream(sr, ch, writes))

    event_one = mixer.start_source(
        "one",
        "one",
        on_finished=lambda source_id: finished.append(source_id),
        on_progress=lambda source_id, seconds: progress.append((source_id, seconds)),
    )
    event_two = mixer.start_source(
        "two",
        "two",
        on_finished=lambda source_id: finished.append(source_id),
        on_progress=None,
    )

    assert event_one.wait(timeout=1.0)
    assert event_two.wait(timeout=1.0)

    # allow mixer thread to flush callbacks
    time.sleep(0.05)
    mixer.close()

    assert {"one", "two"} == set(finished)
    assert writes, "Mixer should have emitted mixed buffers"
    assert any(entry[0] == "one" for entry in progress)
