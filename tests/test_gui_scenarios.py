"""Lightweight scaffolding for GUI scenario tests without launching wx."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List

from sara.ui.playlist_layout import PlaylistLayoutManager


@dataclass
class PendingCall:
    callback: Callable
    args: tuple
    kwargs: dict


class WxScenarioHarness:
    """Collects wx.CallAfter invocations for deterministic execution."""

    def __init__(self) -> None:
        self.pending: List[PendingCall] = []

    def call_after(self, callback: Callable, *args, **kwargs) -> None:
        self.pending.append(PendingCall(callback, args, kwargs))

    def flush(self) -> None:
        while self.pending:
            pending = self.pending.pop(0)
            pending.callback(*pending.args, **pending.kwargs)


class PlaylistScenario:
    """High-level helper modelling playlist add/remove flows."""

    def __init__(self) -> None:
        self.layout = PlaylistLayoutManager()
        self.harness = WxScenarioHarness()
        self.focus_events: List[str] = []

    def add_playlist(self, playlist_id: str) -> None:
        self.layout.add_playlist(playlist_id)
        self.harness.call_after(self._record_focus, playlist_id)

    def remove_current(self) -> None:
        current = self.layout.state.current_id
        if not current:
            return
        self.layout.remove_playlist(current)
        next_focus = self.layout.state.current_id
        if next_focus:
            self.harness.call_after(self._record_focus, next_focus)

    def cycle(self, *, backwards: bool = False) -> None:
        target = self.layout.cycle(backwards=backwards)
        if target:
            self.harness.call_after(self._record_focus, target)

    def reorder(self, new_order) -> None:
        applied = self.layout.apply_order(new_order)
        if applied:
            current = self.layout.state.current_id
            if current:
                self.harness.call_after(self._record_focus, current)

    def _record_focus(self, playlist_id: str) -> None:
        self.focus_events.append(playlist_id)


def test_playlist_scenario_add_remove_flow():
    scenario = PlaylistScenario()
    scenario.add_playlist("music")
    scenario.add_playlist("news")
    scenario.harness.flush()
    assert scenario.focus_events == ["music", "news"]

    scenario.remove_current()
    scenario.harness.flush()
    assert scenario.focus_events[-1] == "news"


def test_playlist_scenario_cycle_order():
    scenario = PlaylistScenario()
    for pid in ("a", "b", "c"):
        scenario.add_playlist(pid)
    scenario.harness.flush()
    scenario.focus_events.clear()

    scenario.cycle()
    scenario.cycle()
    scenario.cycle(backwards=True)
    scenario.harness.flush()
    assert scenario.focus_events == ["b", "c", "b"]


def test_playlist_scenario_reorder_then_remove():
    scenario = PlaylistScenario()
    for pid in ("m1", "m2", "m3"):
        scenario.add_playlist(pid)
    scenario.harness.flush()
    scenario.focus_events.clear()

    scenario.reorder(["m3", "m1"])
    scenario.harness.flush()
    assert scenario.focus_events[-1] == scenario.layout.state.current_id == "m1"

    scenario.remove_current()
    scenario.harness.flush()
    assert scenario.layout.state.order == ["m3", "m2"]
