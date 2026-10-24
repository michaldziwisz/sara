"""Czyste przeliczenia kontrolek punktów miksu, wspólne dla okna i TCP."""

from __future__ import annotations


POINT_ORDER = ("cue", "intro", "outro", "segue", "segue_fade", "overlap", "loop_start", "loop_end")
MIX_POINTS = POINT_ORDER[:6]


def max_allowed_overlap(duration: float, cue: float, relative_segue: float) -> float:
    return max(0.0, (duration or 0.0) - max(0.0, cue or 0.0) - max(0.0, relative_segue))


def assigned_value(key: str, position: float, duration: float, maximum: float) -> float:
    if key == "segue_fade":
        value = max(0.0, position)
    elif key == "overlap":
        value = max(0.0, duration - position)
    else:
        value = position
    if key in {"overlap", "segue_fade"}:
        value = min(value, maximum)
    return value


def nudge_target(key: str, value: float, duration: float, delta: float) -> float:
    if key == "overlap":
        value = max(0.0, (duration or 0.0) - value)
    return value + delta


def consistent_loop_end(start: float, end: float, step: float = 0.01) -> float:
    return start + step if end <= start else end


def collect_mix_values(values: dict[str, float | None], maximum: float) -> dict[str, float | None]:
    results = {key: values.get(key) for key in MIX_POINTS}
    if results["segue"] is not None:
        results["segue"] = max(0.0, results["segue"] - (results["cue"] or 0.0))
    if results["overlap"] is not None:
        results["overlap"] = max(0.0, min(results["overlap"], maximum))
    if results["segue_fade"] is not None:
        results["segue_fade"] = max(0.0, results["segue_fade"])
    return results


def segue_preview_window(fade: float | None, default_fade: float, maximum: float) -> tuple[float, float] | None:
    fade_len = max(0.0, fade) if fade is not None else 0.0
    if fade_len <= 0.0:
        fade_len = default_fade
    if maximum > 0.0:
        fade_len = min(fade_len, maximum)
    if fade_len <= 0.0:
        return None
    return min(4.0, max(0.5, fade_len)), fade_len
