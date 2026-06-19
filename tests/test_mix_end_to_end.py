"""Test integracyjny: deterministyczny miks emisji end-to-end.

Składa elementy z mix_runtime (auto_mix_now / auto_mix_state_process) i sprawdza,
że dla utworu z segue+fade i natywnym wyzwalaczem miks następuje DOKŁADNIE raz,
w punkcie mix_at, z fade'em przyciętym do zapasu — niezależnie od tego, czy
wyzwoli go natywny callback czy progres (siatka bezpieczeństwa). Cel: zafiksować
powtarzalność po refaktorze pętli/miksów.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sara.core.mix_planner import MixPlan
from sara.core.playlist import PlaylistItem, PlaylistKind, PlaylistModel

# Reużyj hosta i atrap z istniejącego zestawu testów jednostkowych.
from test_mix_triggers import _AutoMixPlayer, _MixHost


def _segue_item(tmp_path: Path) -> PlaylistItem:
    return PlaylistItem(
        id="item-1",
        path=tmp_path / "a.wav",
        title="A",
        duration_seconds=12.0,
        cue_in_seconds=0.0,
        segue_seconds=8.0,
    )


def test_native_trigger_mixes_once_at_mix_point(tmp_path):
    """Natywny callback wyzwala miks raz w mix_at; powtórne wywołanie nic nie robi."""
    host = _MixHost(fade=2.0, auto_mix_enabled=True)
    host._supports_mix_trigger = lambda _p: True
    key = ("pl-1", "item-1")

    class _NativePlayer(_AutoMixPlayer):
        def __init__(self):
            super().__init__("dev-1", supports_mix_trigger=True)

        def get_length_seconds(self):
            return 12.0

        def get_position_seconds(self):
            return 8.0  # dokładnie w punkcie miksu

    player = _NativePlayer()
    host._playback = SimpleNamespace(
        auto_mix_state={},
        contexts={key: SimpleNamespace(player=player)},
        update_mix_trigger=lambda *_a, **_k: True,
    )
    host._mix_plans[key] = MixPlan(
        mix_at=8.0, fade_seconds=2.0, base_cue=0.0, effective_duration=12.0, native_trigger=True
    )
    host._mix_trigger_points[key] = 8.0

    started: list[dict] = []
    host._start_next_from_playlist = lambda *_a, **_k: started.append({}) or True

    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    item = _segue_item(tmp_path)
    panel = SimpleNamespace(model=playlist)

    # Pierwsze wyzwolenie (native) — miks następuje, fade = min(2.0, remaining 4.0).
    host._auto_mix_now(playlist, item, panel)
    assert started, "Native powinien wyzwolić miks"
    assert host._playback.auto_mix_state[key] is True
    assert host._mix_plans[key].triggered is True
    assert player.fade_calls == [pytest.approx(2.0)]

    # Drugie wyzwolenie (np. zduplikowany callback) — NIE miksuje ponownie.
    host._auto_mix_now(playlist, item, panel)
    assert len(started) == 1
    assert player.fade_calls == [pytest.approx(2.0)]


def test_progress_safety_net_mixes_once_when_native_silent(tmp_path):
    """Gdy native nie odpalił, progresowa siatka bezpieczeństwa wyzwala miks raz."""
    host = _MixHost(fade=2.0, auto_mix_enabled=True)
    host._supports_mix_trigger = lambda _p: True
    key = ("pl-1", "item-1")

    player = _AutoMixPlayer("dev-1", supports_mix_trigger=True)
    ctx = SimpleNamespace(player=player)
    host._playback = SimpleNamespace(
        auto_mix_state={},
        contexts={key: ctx},
        update_mix_trigger=lambda *_a, **_k: True,
    )

    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    item = _segue_item(tmp_path)
    playlist.add_items([item])
    panel = SimpleNamespace(model=playlist)

    started: list[dict] = []
    host._start_next_from_playlist = lambda *_a, **_k: started.append({}) or True

    # Przed punktem miksu (z zapasem) — siatka czeka na native, nie miksuje.
    host._auto_mix_state_process(panel, item, ctx, seconds=7.0, queued_selection=False)
    assert started == []

    # Po punkcie miksu poza oknem guardu — native milczał, progres wyzwala miks raz.
    host._auto_mix_state_process(panel, item, ctx, seconds=8.5, queued_selection=False)
    assert started, "Progresowa siatka powinna wyzwolić miks"
    assert host._playback.auto_mix_state[key] is True
    assert host._mix_plans[key].triggered is True

    # Kolejne tyknięcie progresu nie miksuje ponownie.
    host._auto_mix_state_process(panel, item, ctx, seconds=9.0, queued_selection=False)
    assert len(started) == 1


def test_native_and_progress_do_not_double_trigger(tmp_path):
    """Native wyzwolił miks — progresowa siatka po nim nie wyzwala drugi raz."""
    host = _MixHost(fade=2.0, auto_mix_enabled=True)
    host._supports_mix_trigger = lambda _p: True
    key = ("pl-1", "item-1")

    class _NativePlayer(_AutoMixPlayer):
        def __init__(self):
            super().__init__("dev-1", supports_mix_trigger=True)

        def get_length_seconds(self):
            return 12.0

        def get_position_seconds(self):
            return 8.0

    player = _NativePlayer()
    ctx = SimpleNamespace(player=player)
    host._playback = SimpleNamespace(
        auto_mix_state={},
        contexts={key: ctx},
        update_mix_trigger=lambda *_a, **_k: True,
    )
    host._mix_plans[key] = MixPlan(
        mix_at=8.0, fade_seconds=2.0, base_cue=0.0, effective_duration=12.0, native_trigger=True
    )
    host._mix_trigger_points[key] = 8.0

    started: list[dict] = []
    host._start_next_from_playlist = lambda *_a, **_k: started.append({}) or True

    playlist = PlaylistModel(id="pl-1", name="P", kind=PlaylistKind.MUSIC)
    item = _segue_item(tmp_path)
    playlist.add_items([item])
    panel = SimpleNamespace(model=playlist)

    host._auto_mix_now(playlist, item, panel)
    assert len(started) == 1

    # Progres po miksie nie może wyzwolić drugiego startu.
    host._auto_mix_state_process(panel, item, ctx, seconds=8.6, queued_selection=False)
    assert len(started) == 1
