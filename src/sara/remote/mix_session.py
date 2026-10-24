"""Stan edycji punktów bez wx, plików i odtwarzaczy. Czasy w sekundach."""

from __future__ import annotations

from sara.core.mix_editing import (
    POINT_ORDER, assigned_value, collect_mix_values, consistent_loop_end,
    max_allowed_overlap, nudge_target,
)


class MixSession:
    def __init__(self, *, duration: float, values: dict[str, float | None], loop_auto_enabled: bool = False):
        self.duration = max(0.0, duration)
        self.values = {key: values.get(key) for key in POINT_ORDER}
        self.cue_base = self.values["cue"] or 0.0
        # Wyłączone pola zachowują wartość tak jak SpinCtrl okna.
        self._stored = {key: value or 0.0 for key, value in self.values.items()}
        if self.values["loop_end"] is None:
            self._stored["loop_end"] = max(self._stored["loop_start"] + 0.1, 0.1)
        self.loop_auto_enabled = loop_auto_enabled
        self.point = "cue"
        self._edge = 0
        self.position = min(self.duration, max(0.0, self.cue_base))
        self._initial = self.values.copy()
        self._undo = []

    @classmethod
    def from_item(cls, item):
        values = {key: getattr(item, key + "_seconds") for key in POINT_ORDER if key != "cue"}
        values["cue"] = item.cue_in_seconds
        if values["segue"] is not None:
            values["segue"] += item.cue_in_seconds or 0.0
        return cls(duration=item.duration_seconds, values=values, loop_auto_enabled=item.loop_auto_enabled)

    @property
    def changed(self) -> bool:
        return self.values != self._initial

    def select(self, point: str) -> None:
        if point in {"next", "prev"}:
            index = POINT_ORDER.index(self.point) + (1 if point == "next" else -1)
            self.point = POINT_ORDER[index % len(POINT_ORDER)]
        else:
            self.point = point

    EDGE_WINDOW = 1.0

    def move(self, position: float) -> None:
        position = max(0.0, min(self.duration, position))
        if position != self.position:  # play_from po shift() podaje tę samą pozycję
            self._edge = 0
        self.position = position

    def shift(self, current: float, delta: float) -> None:
        """Ruch względny kółkiem: najpierw zatrzymanie na brzegu utworu, a dalszy
        ruch w tę samą stronę przeskakuje na drugi koniec (decyzja Michała
        z 25.10.2026: z początku szybko na koniec, np. do ustawienia miksu)."""
        current = max(0.0, min(self.duration, current))
        target = current + delta
        # Przy trwającym odsłuchu pozycja zdąży urosnąć o czas między ząbkami
        # (u Michała ok. 50 ms), więc „jestem na początku” to: poprzedni ruch
        # uderzył w brzeg i od tego czasu minęło mniej niż EDGE_WINDOW.
        at_start = current <= 0.0 or (self._edge == -1 and current < self.EDGE_WINDOW)
        at_end = current >= self.duration or (self._edge == 1 and current > self.duration - self.EDGE_WINDOW)
        if delta < 0 and at_start and target < 0.0:  # MIX_ZAWIJANIE
            target = self.duration + delta
            self._edge = 0
        elif delta > 0 and at_end and target > self.duration:
            target = delta
            self._edge = 0
        else:
            self._edge = -1 if target < 0.0 else 1 if target > self.duration else 0
        self.position = max(0.0, min(self.duration, target))

    def maximum_overlap(self) -> float:
        cue = self.values["cue"]
        cue = self.cue_base if cue is None else cue
        segue = self.values["segue"]
        relative = max(0.0, segue - cue) if segue is not None else 0.0
        return max_allowed_overlap(self.duration, cue, relative)

    def _snapshot(self):
        return self.values.copy(), self._stored.copy(), self.position

    def _record(self, before) -> None:
        if before[0] != self.values:
            self._undo.append(before)

    def _ensure_loop_consistency(self) -> None:
        start, end = self.values["loop_start"], self.values["loop_end"]
        if start is None:
            self.values["loop_end"] = None
        elif end is not None:
            end = consistent_loop_end(start, end)
            self.values["loop_end"] = end
            self._stored["loop_end"] = end

    def _enable(self, key: str) -> None:
        if self.values[key] is not None:
            return
        self.values[key] = self._stored[key]
        if key == "loop_end":
            if self.values["loop_start"] is None:
                self.values["loop_start"] = self._stored["loop_start"]
        if key in {"loop_start", "loop_end"}:
            self._ensure_loop_consistency()

    def _assign(self, position: float) -> None:
        key = self.point
        value = assigned_value(key, position, self.duration, self.maximum_overlap())
        # Takie same granice i precyzja jak SpinCtrlDouble (3 cyfry).
        upper = self.duration if key in {"overlap", "segue_fade"} else max(self.duration, 86400.0)
        self._stored[key] = round(max(0.0, min(upper, value)), 3)
        was_enabled = self.values[key] is not None
        if was_enabled:
            self.values[key] = self._stored[key]
        self._enable(key)
        if key in {"loop_start", "loop_end"}:
            self._ensure_loop_consistency()

    def assign(self) -> None:
        before = self._snapshot()
        self._assign(self.position)
        self._record(before)

    def nudge(self, delta: float) -> None:
        before = self._snapshot()
        self._enable(self.point)
        value = self.values[self.point]
        assert value is not None
        target = nudge_target(self.point, value, self.duration, delta)
        self.move(target)
        self._assign(target)
        self._record(before)

    def clear(self) -> None:
        before = self._snapshot()
        self.values[self.point] = None
        if self.point == "loop_start":
            self.values["loop_end"] = None
        self._record(before)

    def undo(self) -> None:
        if self._undo:
            self.values, self._stored, self.position = self._undo.pop()

    def validation_error(self) -> str | None:
        ordered = [value for key in ("cue", "intro", "outro") if (value := self.values[key]) is not None]
        if any(left >= right for left, right in zip(ordered, ordered[1:])):
            return "kolejnosc"
        start, end = self.values["loop_start"], self.values["loop_end"]
        if start is not None and end is not None and start >= end:
            return "petla"
        return None

    def loop_range(self) -> tuple[float, float] | None:
        start, end = self.values["loop_start"], self.values["loop_end"]
        return (start, end) if start is not None and end is not None and start < end else None

    def mix_values(self) -> dict[str, float | None]:
        return collect_mix_values(self.values, self.maximum_overlap())

    def get_result(self) -> dict:
        result: dict = self.mix_values()
        loop = self.loop_range()
        result["loop"] = {"enabled": bool(loop), "start": loop[0] if loop else None, "end": loop[1] if loop else None}
        result["loop_auto_enabled"] = bool(loop and self.loop_auto_enabled)
        return result
