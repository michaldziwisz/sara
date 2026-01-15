from __future__ import annotations

SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3",
    ".mp2",
    ".mpg",
    ".mpeg",
    ".wav",
    ".flac",
    ".ogg",
    ".oga",
    ".opus",
    ".m4a",
    ".aac",
    ".aiff",
    ".aif",
    ".wma",
    ".wv",
    ".mp4",
}

LOOP_START_TAG = "SARA_LOOP_START"
LOOP_END_TAG = "SARA_LOOP_END"
LOOP_ENABLED_TAG = "SARA_LOOP_ENABLED"
LOOP_AUTO_ENABLED_TAG = "SARA_LOOP_AUTO"
CUE_IN_TAG = "SARA_CUE_IN"
INTRO_TAG = "SARA_INTRO_END"
OUTRO_TAG = "SARA_OUTRO_START"
SEGUE_TAG = "SARA_SEGUE_START"
SEGUE_FADE_TAG = "SARA_SEGUE_FADE_DURATION"
OVERLAP_TAG = "SARA_OVERLAP_DURATION"
REPLAYGAIN_TRACK_GAIN_TAG = "REPLAYGAIN_TRACK_GAIN"
