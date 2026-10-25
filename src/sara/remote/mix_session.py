"""Stan edycji punktów bez wx, plików i odtwarzaczy. Czasy w sekundach."""

from __future__ import annotations

from sara.core.mix_editing import (
    POINT_ORDER, assigned_value, collect_mix_values, consistent_loop_end,
    max_allowed_overlap, nudge_target,
)


class MixSession:
    def __init__(self, *, duration: float, values: dict[str, float | None], loop_auto_enabled: bool = False):
        self.duration = max(0.0, duration)
        # Tylko sesja stołu: okno nadal dopuszcza czasy do co najmniej 24 h.
        self.values = {key: self._bounded_value(key, value) if (value := values.get(key)) is not None else None
                       for key in POINT_ORDER}
        self.cue_base = self.values["cue"] or 0.0
        # Wyłączone pola zachowują wartość tak jak SpinCtrl okna.
        self._stored = {key: value or 0.0 for key, value in self.values.items()}
        if self.values["loop_end"] is None:
            self._stored["loop_end"] = max(self._stored["loop_start"] + 0.1, 0.1)
        self.loop_auto_enabled = loop_auto_enabled
        self.point = "cue"
        self._edge = 0
        self._last_shift = None
        self.position = min(self.duration, max(0.0, self.cue_base))
        self._initial = self.values.copy()
        self._undo = []

    @classmethod
    def from_item(cls, item):
        values = {key: getattr(item, key + "_seconds") for key in POINT_ORDER if key != "cue"}
        values["cue"] = item.cue_in_seconds
        # Ujemny czas to "nieustawione" (StationPlaylist zapisuje -1), nie pozycja w utworze.
        values = {key: None if value is not None and value < 0 else value for key, value in values.items()}
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

    # Ciągły obrót stoi na brzegu. Osobny gest po pół sekundy zawija,
    # a pięć sekund zapasu przed końcem pozwala usłyszeć utwór po przeskoku.
    WRAP_PAUSE = 0.5
    WRAP_LEAD = 5.0
    LOOP_STEP = 0.01

    def move(self, position: float) -> None:
        # Jawne @, Nudge i Undo kasują gest, także przy tej samej liczbie.
        self._edge = 0
        self._last_shift = None
        self.position = max(0.0, min(self.duration, position))

    def shift(self, current: float, delta: float, now: float) -> None:
        """Zatrzymanie na brzegu; przeskok tylko po przerwie od ostatniego ząbka.

        Zegar dostarcza adapter. Dryf odsłuchu nie jest nowym gestem operatora
        i nie kasuje brzegu, nawet gdy pozycja oddaliła się od niego o sekundy.
        """
        current = max(0.0, min(self.duration, current))
        direction = -1 if delta < 0 else 1 if delta > 0 else 0
        same_edge = direction != 0 and self._edge == direction  # MIX_BRZEG_ODSLUCH
        paused = self._last_shift is not None and now - self._last_shift >= self.WRAP_PAUSE
        target = current + delta
        if same_edge and paused:  # MIX_ZAWIJANIE
            target = max(0.0, self.duration - self.WRAP_LEAD) if direction < 0 else 0.0
            self._edge = 0
        elif same_edge:
            target = 0.0 if direction < 0 else self.duration
        else:
            self._edge = -1 if delta < 0 and target <= 0 else 1 if delta > 0 and target >= self.duration else 0
        self._last_shift = now
        self.position = max(0.0, min(self.duration, target))

    def _bounded_value(self, key: str, value: float) -> float:
        # Zostaw miejsce na consistent_loop_end, bez zmiany wspólnej funkcji
        # ani SpinCtrl okna. Krótszy plik ma pętlę od 0 do swojej długości.
        upper = max(0.0, self.duration - self.LOOP_STEP) if key == "loop_start" else self.duration
        # Przycinamy PO zaokrągleniu: round(s, 3) potrafi przekroczyć długość
        # i round(s * 1000) z MixOpen, zwłaszcza przy połówkach milisekund.
        return max(0.0, min(upper, round(value, 3)))  # MIX_GRANICA_PUNKTU

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
            end = min(self.duration, consistent_loop_end(start, end, self.LOOP_STEP))
            self.values["loop_end"] = end
            self._stored["loop_end"] = end

    def _enable(self, key: str) -> None:
        if self.values[key] is not None:
            return
        self.values[key] = self._bounded_value(key, self._stored[key])
        if key == "loop_end":
            if self.values["loop_start"] is None:
                self.values["loop_start"] = self._bounded_value("loop_start", self._stored["loop_start"])
        if key in {"loop_start", "loop_end"}:
            self._ensure_loop_consistency()

    def _assign(self, position: float) -> None:
        key = self.point
        value = assigned_value(key, position, self.duration, self.maximum_overlap())
        self._stored[key] = self._bounded_value(key, value)
        if key in {"overlap", "segue_fade"}:
            self._stored[key] = min(self._stored[key], self.maximum_overlap())
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
        self.move(self.position)

    def validation_error(self) -> str | None:
        # Punkty w tym samym miejscu są dozwolone jak w oknie (np. Cue 0 i Intro 0);
        # błędem jest tylko odwrotna kolejność. Decyzja Michała z 25.10.2026.
        ordered = [value for key in ("cue", "intro", "outro") if (value := self.values[key]) is not None]
        if any(left > right for left, right in zip(ordered, ordered[1:])):  # MIX_KOLEJNOSC
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
