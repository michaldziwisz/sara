"""Adapter sesji punktów do istniejących akcji ramki. Tylko wątek GUI."""

from __future__ import annotations

import math
import re
import time

from sara.core.mix_editing import POINT_ORDER, segue_preview_window
from sara.core.playlist import PlaylistItemStatus
from sara.remote.mix_session import MixSession


class MixControl:
    def __init__(self, frame, panel, item):
        self.frame = frame
        self.panel = panel
        self.item = item
        self.state = MixSession.from_item(item)
        self.preview = "brak"
        self._deadline = None
        self._anchor_started = None
        self._preview_context = None

    def tick(self) -> None:
        if self.preview == "brak":
            return
        playback = self.frame._playback
        if hasattr(playback, "_preview_context") and playback._preview_context is not self._preview_context:
            # Odsłuch skończył się albo użytkownik uruchomił inny z klawiatury.
            self._forget_preview()
        elif self._deadline is not None and time.perf_counter() >= self._deadline:
            self.stop()

    def _forget_preview(self) -> None:
        self.preview = "brak"
        self._anchor_started = None
        self._deadline = None
        self._preview_context = None

    def stop(self) -> None:
        self.tick_if_replaced()
        if self.preview != "brak":
            self.frame._stop_preview()
        self._forget_preview()

    def tick_if_replaced(self) -> None:
        if hasattr(self.frame._playback, "_preview_context"):
            if self.frame._playback._preview_context is not self._preview_context:
                self._forget_preview()

    def current_position(self) -> float:
        if self._anchor_started is None:
            return self.state.position
        elapsed = max(0.0, time.perf_counter() - self._anchor_started)
        return min(self.state.duration, self.state.position + elapsed)

    def response(self) -> str:
        self.tick()
        value = self.state.values[self.state.point]
        return "|".join((str(round(self.current_position() * 1000)), self.state.point,
                         "-" if value is None else str(round(value * 1000)),
                         str(int(self.state.changed)), self.preview))

    def _started(self, mode: str, *, timed: bool = True) -> None:
        self.preview = mode
        self._anchor_started = time.perf_counter() if timed else None
        self._preview_context = getattr(self.frame._playback, "_preview_context", None)

    def play_from(self, position: float, mode: str, loop_range=None) -> bool:
        self.stop()
        self.state.move(position)
        ok = self.frame._playback.start_preview(self.item, self.state.position, loop_range=loop_range)
        if ok:
            self._started(mode)
        return bool(ok)

    def play_mix(self, *, window: bool = False) -> bool:
        values = self.state.mix_values()
        timing = None
        if window:
            if self.state.values["segue"] is None:
                return True  # Jak V w oknie: brak punktu nie uruchamia odsłuchu.
            timing = segue_preview_window(self.state.values["segue_fade"], self.frame._fade_duration,
                                          self.state.maximum_overlap())
            if timing is None:
                return True
            values["_preview_pre_seconds"] = timing[0]
        self.stop()
        ok = self.frame._preview_mix_with_next(self.panel.model, self.item, overrides=values)
        if not ok and timing is not None:
            start = max(0.0, (self.state.values["segue"] or 0.0) - min(timing))
            return self.play_from(start, "punkt")
        if ok:
            self._started("przejscie", timed=False)
            if timing is not None:
                self._deadline = time.perf_counter() + sum(timing)
        return bool(ok)

    def play_point(self) -> bool:
        key = self.state.point
        value = self.state.values[key]
        if value is None:
            return True
        if key in {"segue", "segue_fade"}:
            return self.play_mix(window=True)
        start = max(0.0, self.state.duration - value) if key == "overlap" else value
        return self.play_from(start, "punkt")

    def save_effect(self) -> str:
        key = (self.panel.model.id, self.item.id)
        context = self.frame._playback.contexts.get(key)
        if context is None or self.item.status is PlaylistItemStatus.PAUSED:
            return "nie_gra"
        plan = self.frame._mix_plans.get(key)
        if plan is None or plan.mix_at is None:
            return "brak_przejscia"
        # Tylko odczyt planu po wspólnym zapisie, bez nowej logiki wyzwalania.
        from sara.ui.mix_runtime.now import _current_absolute_position
        position = _current_absolute_position(context, self.item, plan.base_cue)
        remaining = plan.mix_at - position
        return f"przejscie_za={round(remaining * 1000)}" if remaining > 0 else "przejscie_teraz"

    def execute(self, name: str, value: str) -> str:
        self.tick()
        if name == "mixpoint":
            if value.casefold() not in (*POINT_ORDER, "next", "prev"):
                return "ERR syntax"
            self.state.select(value.casefold())
        elif name in {"mixpos", "mixnudge"}:
            prefix = r"[@+-]" if name == "mixpos" else r"[+-]"
            if not re.fullmatch(prefix + r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", value):
                return "ERR syntax"
            amount = float(value[1:] if value.startswith("@") else value)
            if not math.isfinite(amount):
                return "ERR syntax"
            if name == "mixpos":
                position = amount if value.startswith("@") else self.current_position() + amount
                active = self.preview != "brak"
                self.state.move(position)
                if active and not self.play_from(self.state.position, "pozycja"):
                    return "ERR pfl"
            else:
                was_previewing = self.preview != "brak"
                self.stop()
                self.state.nudge(amount)
                if self.state.point in {"segue", "segue_fade"}:
                    if not self.play_mix(window=True):
                        return "ERR pfl"
                elif was_previewing and not self.play_from(self.state.position, "punkt"):
                    return "ERR pfl"
        elif name == "mixset":
            self.state.move(self.current_position())
            self._anchor_started = time.perf_counter() if self._anchor_started is not None else None
            self.state.assign()
        elif name == "mixclear":
            self.state.clear()
        elif name == "mixundo":
            self.stop()
            self.state.undo()
        elif name == "mixplay":
            if self.preview != "brak":
                self.stop()
            else:
                loop = self.state.loop_range()
                if not self.play_from(loop[0] if loop else self.state.position, "pozycja", loop):
                    return "ERR pfl"
        elif name == "mixplaypoint":
            if not self.play_point():
                return "ERR pfl"
        elif name == "mixplaymix":
            if not self.play_mix():
                return "ERR pfl"
        elif name == "mixstop":
            self.stop()
        return self.response()


MIX_COMMANDS = {"mixopen", "mixinfo", "mixpos", "mixpoint", "mixset", "mixnudge", "mixclear",
                "mixplay", "mixplaypoint", "mixplaymix", "mixstop", "mixundo", "mixsave", "mixcancel"}


def execute_mix(session, name: str, equals: str, value: str) -> str:
    from sara.remote.commands import clean_text, milliseconds

    frame = session.frame
    if name != "mixopen" and session.mix is None:
        return "ERR nosession"
    if bool(equals) != (name in {"mixpos", "mixpoint", "mixnudge"}):
        return "ERR syntax"
    if name == "mixopen":
        if getattr(frame, "_remote_mix_owner", None) is not None:
            return "ERR session"
        if getattr(frame, "_mix_points_dialog_open", False):
            return "ERR busy"
        panel = session._main_panel()
        index = panel.get_focused_index() if panel is not None else -1
        if panel is None or not 0 <= index < len(panel.model.items):
            return "ERR empty"
        item = panel.model.items[index]
        session.mix = MixControl(frame, panel, item)
        frame._remote_mix_owner = session
        playing = (panel.model.id, item.id) in frame._playback.contexts and item.status is not PlaylistItemStatus.PAUSED
        return "|".join(("OK", str(index), str(int(playing)), milliseconds(item.duration_seconds),
                         clean_text(item.artist, separator="|"), clean_text(item.title, separator="|")))
    mix = session.mix
    if name == "mixsave":
        error = mix.state.validation_error()
        if error is not None:
            return "ERR invalid|" + error
        from sara.ui.controllers.mix.points import apply_mix_point_result
        apply_mix_point_result(frame, mix.panel.model.id, mix.item, mix.state.get_result())
        effect = mix.save_effect()
        session.close()
        return "OK|" + effect
    if name == "mixcancel":
        session.close()
        return "OK"
    return mix.execute(name, value)
