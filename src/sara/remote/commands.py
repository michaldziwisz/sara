"""Protokół tekstowy bez zależności od wx; wywoływany wyłącznie w wątku GUI."""

from __future__ import annotations

import copy
import csv
import io
import re
from dataclasses import fields
from sara import __version__

from sara.core.playlist import PlaylistItemStatus, PlaylistItemType, PlaylistKind
from sara.ui.controllers.playback.next_item import decide_next_item
from sara.remote.main_playlist import main_panel, background_selection
from sara.remote.hold import get_hold_controller
from sara.remote.mix_control import MIX_COMMANDS, execute_mix


def app_version() -> str:
    # Wersja zawsze z kodu: metadane instalacji bywają przestarzałe
    # (na głównej `pip show sara` podawał 0.0.11 przy kodzie 0.0.37),
    # a zamrożony program może ich nie mieć wcale.
    return __version__


def clean_text(value: object, *, separator: str = "") -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").replace("\x00", " ")
    return text.replace(separator, " ") if separator else text


def milliseconds(seconds: float | None) -> str:
    return str(round(max(0.0, seconds or 0.0) * 1000))


class CommandSession:
    """Stan pojedynczego klienta (niezależny znacznik zmiany playlisty)."""

    def __init__(self, frame, *, program_version: str | None = None) -> None:
        self.frame = frame
        self.version = program_version if program_version is not None else app_version()
        self._last_snapshot = None
        self.mix = None

    def close(self) -> None:
        """Rozłączenie klienta porzuca tylko jego własną sesję punktów."""
        if self.mix is not None:
            self.mix.stop()
            self.mix = None
        if getattr(self.frame, "_remote_mix_owner", None) is self:
            self.frame._remote_mix_owner = None

    def execute_line(self, line: str) -> list[str]:
        if "=" in line and "," in line:
            return ["ERR syntax"]
        result = []
        for command in line.split(","):
            result.extend(self.execute(command.strip()))
        return result

    def _main_panel(self):
        return main_panel(self.frame)

    def _current(self):
        panel = self._main_panel()
        if panel is None:
            return None
        contexts = self.frame._playback.contexts
        writer = getattr(self.frame, "_now_playing_writer", None)
        key = getattr(writer, "_current_key", None)
        keys = [key] if key is not None and key in contexts else []
        keys.extend(k for k in reversed(contexts) if k != key)
        for candidate in keys:
            if candidate[0] == panel.model.id:
                item = panel.model.get_item(candidate[1])
                if item:
                    return panel.model, item
        return None

    def _snapshot(self):
        panel = self._main_panel()
        if panel is None:
            return ()
        model = panel.model
        # Postęp czasu nie oznacza edycji playlisty. Pozostałe pola obejmują
        # m.in. kolejkę, status, kolejność, metadane, cue, pętlę i break.
        items = tuple(
            tuple(getattr(item, field.name) for field in fields(item) if field.name != "current_position")
            for item in model.items
        )
        return model.id, model.name, tuple(model.get_configured_slots()), items

    def _status(self, *, acknowledge: bool = False) -> str:
        active = []
        panel = self._main_panel()
        for playlist_id, item_id in self.frame._playback.contexts:
            if panel and playlist_id == panel.model.id:
                item = panel.model.get_item(item_id)
                if item:
                    active.append(item)
        playing = any(item.status is not PlaylistItemStatus.PAUSED for item in active)
        paused = any(item.status is PlaylistItemStatus.PAUSED for item in active)
        jingles = getattr(self.frame, "_jingles", None)
        players = [getattr(jingles, "_main_player", None)] + list(getattr(jingles, "_overlay_players", []))
        cart = any(player is not None and player.is_playing() for player in players)
        snapshot = self._snapshot()
        changed = snapshot != self._last_snapshot
        if acknowledge:
            self._last_snapshot = snapshot
        return "".join(str(int(flag)) for flag in (
            playing, self.frame._auto_mix_enabled, False, False, paused, cart, changed,
        ))

    @staticmethod
    def _name(item) -> str:
        if item is None:
            return ""
        return clean_text(f"{item.artist} - {item.title}" if item.artist else item.title)

    def _next_in_panel(self, panel):
        model = panel.model
        if not model.items:
            return None
        if self.frame._auto_mix_enabled and model.kind is PlaylistKind.MUSIC:
            tracker = copy.deepcopy(self.frame._auto_mix_tracker)
            hold = [key for key, state in self.frame._playback.auto_mix_state.items()
                    if key[0] == model.id and state == "loop_hold"]
            if hold:
                tracker.set_last_started(model.id, hold[-1][1])
            current = self.frame._get_playback_context(model.id)
            item = model.get_item(current[0][1]) if current else None
            if item and item.break_after and item.status is PlaylistItemStatus.PLAYING:
                return model.items[(model.index_of(item.id) + 1) % len(model.items)]
            index = tracker.next_index(model, break_resume_index=model.break_resume_index)
            if item and model.items[index].id == item.id:
                for _ in model.items:
                    index = (index + 1) % len(model.items)
                    if model.items[index].id != item.id and model.items[index].status is not PlaylistItemStatus.PLAYING:
                        break
            return model.items[index]
        decision = decide_next_item(
            model,
            panel_selected_indices=panel.get_selected_indices(),
            panel_focus_index=panel.get_focused_index(),
            ignore_ui_selection=False,
            last_started_item_id=self.frame._last_started_item_id.get(model.id),
            break_target_index=model.break_resume_index,
            restart_playing=False,
            current_playing_item_id=None,
        )
        # begin_next_item ma własny fallback; wykonujemy go na kopii, bez
        # konsumowania kolejki i bez zmiany statusu utworu w prawdziwym modelu.
        return copy.deepcopy(model).begin_next_item(decision.preferred_item_id)

    def _next(self):
        if self.frame._alternate_play_next:
            order = [pid for pid in self.frame._layout.state.order if pid in self.frame._playlists]
            if not order:
                return None
            start = self.frame._current_index % len(order)
            panels = [self.frame._playlists[order[(start + offset) % len(order)]] for offset in range(len(order))]
        else:
            panel = self._main_panel()
            panels = [panel] if panel else []
        for panel in panels:
            if panel.model.kind is PlaylistKind.MUSIC:
                item = self._next_in_panel(panel)
                if item:
                    return item
        return None

    @staticmethod
    def _selected_index(panel) -> int:
        if panel is None:
            return -1
        selected = panel.get_selected_indices()
        focused = panel.get_focused_index()
        index = focused if focused in selected else (selected[0] if selected else -1)
        return index if 0 <= index < len(panel.model.items) else -1

    def _hotkey(self, action: str) -> None:
        from sara.ui.controllers.playlists.hotkeys import run_playlist_action
        panel = self._main_panel()
        if panel is not None:
            run_playlist_action(self.frame, panel, action)

    def _play_focused(self) -> bool:
        """Play w trybie ręcznym działa jak Enter na głównej playliście.

        Enter (swap_play_select) woła play_item_direct: kolejka zaznaczonych ma
        pierwszeństwo i gra po kolei, bez kolejki gra podświetlony utwór.
        Automiks i naprzemienne playlisty zostają przy „Odtwórz następny”.
        Podświetlony utwór, który już gra, nie jest uruchamiany od nowa: Enter
        by go zrestartował, a z klawisza stołu łatwo nacisnąć dwa razy.
        Zwraca False, gdy obsługę ma przejąć „Odtwórz następny”.
        """
        frame = self.frame
        if frame._auto_mix_enabled or frame._alternate_play_next:
            return False
        panel = self._main_panel()
        if panel is None:
            return False
        model = panel.model
        has_queue = any(item.is_selected for item in model.items)
        index = panel.get_focused_index()
        if not has_queue and not 0 <= index < len(model.items):
            return False
        if has_queue:
            item = next(item for item in model.items if item.is_selected)
        else:
            item = model.items[index]
            if item.status is PlaylistItemStatus.PLAYING and (model.id, item.id) in frame._playback.contexts:
                return True
        try:
            from sara.ui.services.nvda_sleep import notify_nvda_play_next
            notify_nvda_play_next()
        except Exception:  # pylint: disable=broad-except
            pass
        frame._play_item_direct(model.id, item.id)
        return True

    def execute(self, command: str) -> list[str]:
        hold = get_hold_controller(self.frame)
        with background_selection(self.frame):
            hold.sync()
            try:
                return self._execute(command)
            finally:
                hold.sync()

    def _execute(self, command: str) -> list[str]:
        name, equals, value = command.partition("=")
        name = name.strip().casefold()
        value = value.strip()
        if name in MIX_COMMANDS:
            return [execute_mix(self, name, equals, value)]
        if equals and name not in {"selectindex", "trackinfo", "trackinfoex", "hold"}:
            return ["ERR unknown"]
        if name == "hold":
            hold = get_hold_controller(self.frame)
            if equals:
                if value not in {"0", "1"}:
                    return ["ERR syntax"]
                hold.set_enabled(value == "1")
            return [hold.response()]
        if name == "helo":
            return [f"SARA v{self.version}"]
        if name == "stat":
            return [self._status(acknowledge=True)]
        if name in {"play", "skip"}:
            from sara.ui.controllers.playback.navigation import play_next_for_panel
            if name == "play" and self._play_focused():
                return [self._status()]
            play_next_for_panel(self.frame, self._main_panel(), activate_alternate=False)
            return [self._status()]
        if name in {"stop", "instant stop", "pause"}:
            if name == "pause":
                panel = self._main_panel()
                entry = self.frame._get_playback_context(panel.model.id) if panel else None
                item = panel.model.get_item(entry[0][1]) if entry else None
                if item and item.status is PlaylistItemStatus.PAUSED:
                    return [self._status()]
            self._hotkey({"stop": "fade", "instant stop": "stop", "pause": "pause"}[name])
            return [self._status()]
        if name in {"autoon", "autooff", "auto"}:
            enabled = not self.frame._auto_mix_enabled if name == "auto" else name == "autoon"
            self.frame._set_auto_mix_enabled(enabled, panel=self._main_panel())
            return [self._status()]
        if name in {"this", "rem", "elap", "currindex"}:
            current = self._current()
            if name == "this":
                return [self._name(current[1] if current else None)]
            if name == "currindex":
                panel = self._main_panel()
                return [str(panel.model.index_of(current[1].id)) if current and panel and panel.model.id == current[0].id else "-1"]
            if not current:
                return ["0"]
            item = current[1]
            seconds = item.current_position if name == "elap" else item.effective_duration_seconds - item.current_position
            return [milliseconds(seconds)]
        if name == "next":
            return [self._name(self._next())]
        if name == "lastindex":
            panel = self._main_panel()
            return [str(len(panel.model.items) - 1) if panel else "-1"]
        if name == "selectindex":
            panel = self._main_panel()
            index = self._selected_index(panel)
            if equals:
                if not panel or not panel.model.items:
                    return ["-1"]
                if value in {"+", "-"}:
                    if index < 0:
                        index = panel.get_focused_index()
                    index = max(0, min(len(panel.model.items) - 1, index + (1 if value == "+" else -1)))
                elif re.fullmatch(r"[0-9]+", value):
                    index = int(value)
                else:
                    return ["ERR syntax"]
                if not 0 <= index < len(panel.model.items):
                    return ["ERR range"]
                # Focus dotyczy wiersza ListCtrl, nie okna (bez SetFocus/Raise).
                panel.select_index(index)
            return [str(index)]
        if name == "checktoggle":
            panel = self._main_panel()
            if panel is None:
                return ["-1"]
            index = panel.get_focused_index()
            if not 0 <= index < len(panel.model.items):
                index = self._selected_index(panel)
            if index < 0:
                return ["-1"]
            item = panel.model.items[index]
            self.frame._on_toggle_selection(panel.model.id, item.id)
            return [str(int(item.is_selected))]
        if name in {"trackinfo", "trackinfoex"}:
            match = re.fullmatch(r"([0-9]+)-([0-9]+)", value) if equals else None
            if not match:
                return ["ERR syntax"]
            start, end = map(int, match.groups())
            panel = self._main_panel()
            if not panel or not 0 <= start <= end < len(panel.model.items):
                return ["ERR range"]
            rows = []
            for index in range(start, end + 1):
                item = panel.model.items[index]
                if name == "trackinfoex":
                    rows.append("|".join((str(index), str(int(item.is_selected)), item.status.name.lower(),
                                          clean_text(item.artist, separator="|"), clean_text(item.title, separator="|"),
                                          milliseconds(item.effective_duration_seconds), str(int(item.break_after)))))
                else:
                    stream = io.StringIO(newline="")
                    csv.writer(stream, lineterminator="\r\n").writerow((
                        index, 1 if item.item_type is PlaylistItemType.SPOT else 0,
                        clean_text(item.artist), clean_text(item.title), "",
                        milliseconds(item.effective_duration_seconds), milliseconds(item.intro_seconds),
                        milliseconds(item.outro_seconds), "", clean_text(item.path),
                    ))
                    rows.append(stream.getvalue().removesuffix("\r\n"))
            return rows
        return ["ERR unknown"]
