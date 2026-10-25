"""Kontrola zapór TCP, wyboru głównej playlisty i wstrzymania Hold.

Uruchom pod Xvfb: python3 scripts/check_remote_mutations.py
Każdy mutant jest ładowany wyłącznie do pamięci osobnego procesu pytest.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = (
    (
        "preload-nie-wraca-do-kolejki", "sara.ui.controllers.playback.automix",
        'sequence=enabled',
        'sequence=True',
        "tests/test_playback_preload_handoff.py::test_disabling_automix_prepares_manual_candidate",
    ),
    (
        "preload-gubienie-playera", "sara.ui.playback.device_selection",
        'prepared = take_preloaded(playlist.id, device_id) if take_preloaded else None',
        'prepared = None',
        "tests/test_playback_preload_handoff.py::test_mix_start_reuses_prepared_factory_player_without_slow_open[True]",
    ),
    (
        "preload-tylko-automiks", "sara.ui.controllers.playback.start",
        '    if playlist.kind is PlaylistKind.MUSIC:\n        try:\n            frame._playback.schedule_next_preload',
        '    if frame._auto_mix_enabled and playlist.kind is PlaylistKind.MUSIC:\n        try:\n            frame._playback.schedule_next_preload',
        "tests/test_playback_preload_handoff.py::test_mix_start_reuses_prepared_factory_player_without_slow_open[False]",
    ),
    (
        "preload-ebu-zapisuje-przygotowany", "sara.ui.services.auto_loudness",
        'if any(path_key(path) == key for path in preloaded_paths()):',
        'if False:',
        "tests/test_auto_loudness.py::test_playing_gain_unchanged_and_save_deferred[prepared_controller]",
    ),
    (
        "loudness-bez-ogranicznika-tp", "sara.core.loudness",
        "gain = min(target - integrated, -1.0 - peak)  # LOUDNESS_TRUE_PEAK",
        "gain = target - integrated  # mutant: brak ogranicznika TP",
        "tests/test_loudness_peak.py::test_gain_is_true_peak_limited[-30--2-1]",
    ),
    (
        "loudness-zmienia-grajacego", "sara.ui.services.auto_loudness",
        "        self._pending[key] = (path, gain, marker)",
        "        for context in self.frame._playback.contexts.values():\n            context.player.set_gain_db(gain)\n        self._pending[key] = (path, gain, marker)",
        "tests/test_auto_loudness.py::test_playing_gain_unchanged_and_save_deferred[playing]",
    ),
    (
        "loudness-pomija-znacznik", "sara.ui.services.auto_loudness",
        "if item.sara_loudness:  # LOUDNESS_MARKER", "if False:  # mutant: ponowny pomiar",
        "tests/test_auto_loudness.py::test_marker_skips_measurement_including_m3u_reload",
    ),
    (
        "loudness-pomiar-w-gui", "sara.ui.services.auto_loudness",
        "                result = loudness.measure_normalization(path, standard=loudness.LoudnessStandard.EBU)",
        "                self._call_after(lambda key=key, path=path: self._finished(key, path, loudness.measure_normalization(path, standard=loudness.LoudnessStandard.EBU)))\n                continue",
        "tests/test_auto_loudness.py::test_three_files_are_measured_off_gui_and_persisted",
    ),
    (
        "loudness-zapisuje-otwarty-plik", "sara.ui.services.auto_loudness",
        "if self._path_in_use(key):", "if False:  # mutant: zapis mimo kontekstu",
        "tests/test_auto_loudness.py::test_playing_gain_unchanged_and_save_deferred[paused]",
    ),
    (
        "mix-zapis-bez-propagacji", "sara.ui.controllers.mix.points",
        "        frame._propagate_mix_points_for_path(\n",
        "        (lambda **kwargs: None)(\n",
        "tests/test_remote_mix_gui.py::test_window_and_session_write_identical_tags_model_and_propagation",
    ),
    (
        "mix-zapis-bez-przeliczenia", "sara.ui.controllers.mix.points",
        "    frame._apply_mix_trigger_to_playback(playlist_id=playlist_id, item=item, panel=panel)",
        "    pass  # mutant: stary plan pozostaje",
        "tests/test_remote_mix.py::test_save_reschedules_playing_track_and_reports_actual_plan",
    ),
    (
        "mix-bez-walidacji", "sara.remote.mix_control",
        "error = mix.state.validation_error()", "error = None",
        "tests/test_remote_mix.py::test_invalid_order_keeps_file_model_and_session",
    ),
    (
        "mix-cancel-zapisuje", "sara.remote.mix_control",
        '    if name == "mixcancel":\n        session.close()',
        '    if name == "mixcancel":\n        from sara.ui.controllers.mix.points import apply_mix_point_result\n        apply_mix_point_result(frame, mix.panel.model.id, mix.item, mix.state.get_result())\n        session.close()',
        "tests/test_remote_mix.py::test_cancel_does_not_write_and_stops_preview",
    ),
    (
        "mix-bez-zawijania", "sara.remote.mix_session",
        "if same_edge and paused:  # MIX_ZAWIJANIE",
        "if False:  # mutant: kółko staje na początku",
        "tests/test_remote_mix.py::test_navigation_clamp_set_clear_and_undo",
    ),
    (
        "mix-zawijanie-bez-odsluchu", "sara.remote.mix_session",
        "same_edge = direction != 0 and self._edge == direction  # MIX_BRZEG_ODSLUCH",
        "same_edge = direction != 0 and self._edge == direction and current in (0.0, self.duration)",
        "tests/test_remote_mix.py::test_wrap_left_while_preview_is_playing",
    ),
    (
        "mix-przeskok-bez-przerwy", "sara.remote.mix_session",
        "if same_edge and paused:  # MIX_ZAWIJANIE",
        "if same_edge:  # mutant: ciągły obrót przeskakuje",
        "tests/test_remote_mix.py::test_navigation_clamp_set_clear_and_undo",
    ),
    (
        "mix-bez-wznowienia-po-eof", "sara.remote.mix_control",
        "self._resume_preview = natural_end  # MIX_WZNOWIENIE_EOF",
        "self._resume_preview = False  # mutant: kółko milczy po EOF",
        "tests/test_remote_mix.py::test_natural_preview_end_resumes_on_wheel",
    ),
    (
        "mix-punkt-poza-utworem", "sara.remote.mix_session",
        "return max(0.0, min(upper, round(value, 3)))  # MIX_GRANICA_PUNKTU",
        "return max(0.0, round(value, 3))  # mutant: brak granicy długości",
        "tests/test_remote_mix.py::test_log_sequence_loop_start_at_eof_then_nudge",
    ),
    (
        "mix-rowne-punkty-odrzucone", "sara.remote.mix_session",
        "if any(left > right for left, right in zip(ordered, ordered[1:])):  # MIX_KOLEJNOSC",
        "if any(left >= right for left, right in zip(ordered, ordered[1:])):  # mutant: Cue = Intro to błąd",
        "tests/test_remote_mix.py::test_equal_cue_and_intro_saves_from_table",
    ),
    (
        "bind-wszystkie-interfejsy", "sara.remote.server",
        'super().__init__(("127.0.0.1", port), _ClientHandler)',
        'super().__init__(("0.0.0.0", port), _ClientHandler)',
        "tests/test_remote_server.py::test_socket_bind_is_loopback_and_other_local_address_cannot_connect",
    ),
    (
        "wykonanie-w-watku-klienta", "sara.remote.server",
        "            self._call_after(invoke)\n            return future.result(timeout=self.timeout)",
        "            return function(*args)",
        "tests/test_remote_server.py::test_real_socket_commands_run_on_main_thread",
    ),
    (
        "zwolnienie-recznych-przerw", "sara.remote.hold",
        "for key in list(self.owned_breaks):",
        "for key in [(p.model.id, i.id) for p in self.frame._playlists.values() for i in p.model.items if i.break_after]:",
        "tests/test_remote_hold.py::test_release_preserves_manual_break",
    ),
    (
        "wylaczony-zegar-hold", "sara.ui.services.remote_control",
        "timer.Start(100)", "pass  # mutant: brak zegara",
        "tests/test_remote_main_hold_gui.py::test_timer_protects_keyboard_started_track_within_150ms",
    ),
    (
        "przerwa-bez-zdjecia-wyzwalacza", "sara.ui.controllers.playlists.hotkeys",
        "mix_trigger_seconds=None,", "mix_trigger_seconds=current_item.segue_seconds,",
        "tests/test_remote_hold.py::test_hold_removes_trigger_and_finish_stays_stopped[True]",
    ),
    (
        "biezaca-zamiast-glownej", "sara.remote.commands",
        "return main_panel(self.frame)", "return self.frame._get_current_music_panel()",
        "tests/test_remote_main_playlist.py::test_news_active_all_commands_target_main_without_activation",
    ),
    (
        "play-przez-sciezke-newsow", "sara.remote.commands",
        "play_next_for_panel(self.frame, self._main_panel(), activate_alternate=False)",
        "self.frame._on_global_play_next(None)",
        "tests/test_remote_main_hold_gui.py::test_news_save_focus_remote_play_never_presses_save",
    ),
    (
        "zaznaczenie-aktywuje-playliste", "sara.remote.main_playlist",
        "blockers.append(wx.EventBlocker(control, wx.EVT_LIST_ITEM_SELECTED.typeId))", "pass",
        "tests/test_remote_main_hold_gui.py::test_real_panel_selection_events_do_not_activate_main",
    ),
    (
        "auto-on-na-aktywnej", "sara.remote.commands",
        "self.frame._set_auto_mix_enabled(enabled, panel=self._main_panel())",
        "self.frame._set_auto_mix_enabled(enabled)",
        "tests/test_remote_main_playlist.py::test_auto_on_starts_main_not_active_playlist",
    ),
    (
        "play-bez-entera", "sara.remote.commands",
        'if name == "play" and self._play_focused():',
        "if False:",
        "tests/test_remote_play_focused.py::test_manual_play_starts_highlighted_track_like_enter",
    ),
    (
        "play-restartuje-grajacy", "sara.remote.commands",
        "                return True\n        try:\n            from sara.ui.services.nvda_sleep",
        "                pass\n        try:\n            from sara.ui.services.nvda_sleep",
        "tests/test_remote_play_focused.py::test_manual_play_does_not_restart_highlighted_playing_track",
    ),
)


def main() -> int:
    env = dict(os.environ, WX_RUN_GUI_TESTS="1")
    tests = list(dict.fromkeys(entry[-1] for entry in MUTATIONS))
    control = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
                             cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    print("Kontrola dodatnia:", control.stdout, control.stderr)
    if control.returncode != 0 or f"{len(tests)} passed" not in control.stdout:
        print("BŁĄD: testy kontrolne nie przeszły lub zostały pominięte")
        return 1
    failed = False
    for name, module_name, old, new, test in MUTATIONS:
        program = f"""
import importlib
import sys
from pathlib import Path
sys.path.insert(0, {str(ROOT / 'src')!r})
module = importlib.import_module({module_name!r})
path = Path(module.__file__)
source = path.read_text(encoding='utf-8')
assert source.count({old!r}) == 1
exec(compile(source.replace({old!r}, {new!r}), str(path), 'exec'), module.__dict__)
import pytest
raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', {test!r}]))
"""
        result = subprocess.run([sys.executable, "-c", program], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=60)
        killed = result.returncode == 1 and "1 failed" in result.stdout and "AssertionError" in result.stdout
        print(f"{name}: {'ZABITY' if killed else 'BŁĄD WERYFIKACJI'} (exit={result.returncode})")
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        failed |= not killed
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
