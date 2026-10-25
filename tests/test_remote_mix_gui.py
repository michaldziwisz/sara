# Importy GUI dopiero po sprawdzeniu dostępności wx i ekranu.
# ruff: noqa: E402
from __future__ import annotations

from dataclasses import asdict
from unittest.mock import Mock

import pytest
from mutagen.apev2 import APEv2

wx = pytest.importorskip("wx")
if not wx.App.IsDisplayAvailable():
    pytest.skip("wx display required", allow_module_level=True)

from sara.remote.commands import CommandSession
from sara.ui.controllers.mix import points
from sara.ui.dialogs.mix_point_dialog import MixPointEditorDialog
from sara.ui.services.remote_control import stop_remote_control
from test_remote_mix import mix_frame as mix_frame
from test_remote_mix import open_mix, request, set_point


@pytest.fixture(scope="module")
def app():
    yield wx.GetApp() or wx.App()


def make_dialog(item):
    return MixPointEditorDialog(None, title="Punkty miksu", duration_seconds=item.duration_seconds,
        cue_in_seconds=item.cue_in_seconds, intro_seconds=item.intro_seconds,
        outro_seconds=item.outro_seconds, segue_seconds=item.segue_seconds,
        segue_fade_seconds=item.segue_fade_seconds, overlap_seconds=item.overlap_seconds,
        loop_start_seconds=item.loop_start_seconds, loop_end_seconds=item.loop_end_seconds,
        loop_auto_enabled=item.loop_auto_enabled, on_preview=lambda *a: True,
        on_stop_preview=lambda: None, track_path=item.path, initial_replay_gain=None)


def test_window_and_session_write_identical_tags_model_and_propagation(app, mix_frame):
    frame, item, _ = mix_frame
    original = asdict(item)
    original_bytes = item.path.read_bytes()
    dialog = make_dialog(item)
    try:
        # Zwykłe kontrolki okna, bez adaptera sesji.
        dialog._suppress_auto_preview = True
        for key, value in [("cue", 3), ("intro", 12), ("outro", 100), ("segue", 110),
                           ("segue_fade", 2), ("overlap", 10), ("loop_start", 20), ("loop_end", 30)]:
            row = dialog._rows[key]
            row.checkbox.SetValue(True)
            row.spin.SetValue(value)
        result = dialog.get_result()
        points.apply_mix_point_result(frame, "music", item, result)
        window_model = asdict(item)
        window_tags = APEv2(item.path).pprint()
        duplicate = frame._playlists["second"].model.items[0]
        window_duplicate = asdict(duplicate)
        for key, value in original.items():
            setattr(item, key, value)
        for field in ("cue_in_seconds", "intro_seconds", "outro_seconds", "segue_seconds",
                      "segue_fade_seconds", "overlap_seconds"):
            setattr(duplicate, field, None)
        item.path.write_bytes(original_bytes)
        session = open_mix(frame)
        for key, value in [("cue", 3), ("intro", 11.9), ("outro", 100), ("segue", 110),
                           ("segue_fade", 2), ("overlap", 115), ("loop_start", 20), ("loop_end", 30)]:
            set_point(session, key, value)
        request(session, "MixPoint=intro")
        request(session, "MixNudge=+0.1")
        assert request(session, "MixSave").startswith("OK|")
        assert asdict(item) == window_model
        assert APEv2(item.path).pprint() == window_tags
        assert asdict(duplicate) == window_duplicate
        assert duplicate.cue_in_seconds == 3
        assert duplicate.segue_seconds == 107
    finally:
        dialog.Destroy()
        wx.Yield()


@pytest.mark.parametrize("key,position", [("cue", 4), ("intro", 10), ("outro", 100),
    ("segue", 110), ("segue_fade", 3), ("overlap", 119), ("loop_start", 15), ("loop_end", 25)])
def test_assign_and_nudge_match_dialog(app, mix_frame, key, position):
    frame, item, _ = mix_frame
    # Punkt segue zostawia miejsce na fade i overlap.
    item.segue_seconds = 105
    dialog = make_dialog(item)
    try:
        session = open_mix(frame)
        set_point(session, key, position)
        dialog._suppress_auto_preview = True
        dialog._active_row_key = key
        dialog._assign_active_point(position=position)
        dialog._nudge_position(0.1, assign=True)
        request(session, "MixNudge=+0.1")
        assert session.mix.state.get_result() == dialog.get_result()
    finally:
        dialog.Destroy()
        wx.Yield()


@pytest.mark.parametrize("operations", [
    [("clear", "cue", 0), ("set", "segue", 50), ("set", "overlap", 0)],
    [("clear", "segue", 0), ("set", "overlap", 0), ("set", "cue", 20)],
    [("set", "segue", 90), ("set", "segue_fade", 30), ("set", "segue", 120)],
    [("set", "loop_end", 20), ("set", "loop_start", 25), ("clear", "loop_start", 0), ("nudge", "loop_end", -0.1)],
    [("set", "intro", 20), ("clear", "intro", 0), ("nudge", "intro", 0.1)],
    [("nudge", "overlap", -0.1), ("nudge", "segue_fade", 0.1)],
])
def test_edit_sequences_match_dialog(app, mix_frame, operations):
    frame, item, _ = mix_frame
    dialog = make_dialog(item)
    dialog._suppress_auto_preview = True
    try:
        session = open_mix(frame)
        for action, key, value in operations:
            request(session, "MixPoint=" + key)
            dialog._active_row_key = key
            if action == "set":
                set_point(session, key, value)
                dialog._assign_active_point(position=value)
            elif action == "clear":
                request(session, "MixClear")
                dialog._rows[key].checkbox.SetValue(False)
                dialog._toggle_point(key)
            else:
                request(session, f"MixNudge={value:+}")
                dialog._nudge_position(value, assign=True)
            assert session.mix.state.get_result() == dialog.get_result(), (action, key, value)
    finally:
        dialog.Destroy()
        wx.Yield()


def test_modal_window_busy_flag_is_active_inside_event_loop(app, mix_frame, monkeypatch):
    frame, item, _ = mix_frame
    # Ramka fixture nie jest wx.Window, ale cykl życia to prawdziwy kontroler.
    def modal(_self):
        assert request(CommandSession(frame), "MixOpen") == "ERR busy"
        return wx.ID_CANCEL
    dialog = make_dialog(item)
    monkeypatch.setattr(dialog, "ShowModal", lambda: modal(dialog))
    monkeypatch.setattr(points, "MixPointEditorDialog", lambda *a, **kw: dialog)
    points.on_mix_points_configure(frame, "music", item.id)
    assert not frame._mix_points_dialog_open
    assert request(CommandSession(frame), "MixOpen").startswith("OK|")


def test_remote_session_prevents_second_editor_and_shutdown_cancels(app, mix_frame, monkeypatch):
    frame, item, _ = mix_frame
    session = open_mix(frame)
    constructor = Mock()
    monkeypatch.setattr(points, "MixPointEditorDialog", constructor)
    points.on_mix_points_configure(frame, "music", item.id)
    constructor.assert_not_called()
    set_point(session, "intro", 12)
    request(session, "MixPlay")
    stop_remote_control(frame)
    assert request(session, "MixInfo") == "ERR nosession"
    assert item.intro_seconds is None
    frame._stop_preview.assert_called()


def test_dialog_keeps_its_existing_bounds_and_loop_consistency(app, mix_frame):
    _, item, _ = mix_frame
    dialog = make_dialog(item)
    try:
        dialog._suppress_auto_preview = True
        for key in ("cue", "intro", "outro", "segue", "loop_start", "loop_end"):
            assert dialog._rows[key].spin.GetMax() == 86400.0
        for key in ("loop_start", "loop_end"):
            row = dialog._rows[key]
            row.checkbox.SetValue(True)
            row.spin.SetValue(item.duration_seconds)
        dialog._ensure_loop_consistency()
        # Granica sesji stołu NIE zmieniła zachowania okna ani wspólnej funkcji.
        assert dialog._rows["loop_end"].spin.GetValue() == pytest.approx(item.duration_seconds + 0.01)
    finally:
        dialog.Destroy()
        wx.Yield()
