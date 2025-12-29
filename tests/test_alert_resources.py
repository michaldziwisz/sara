from importlib.resources import files


def test_alert_wav_resources_are_packaged_and_readable():
    for filename in ("beep.wav", "track_end_alert.wav"):
        resource = files("sara.audio").joinpath("media", filename)
        with resource.open("rb") as fh:
            header = fh.read(4)
        assert header == b"RIFF"

