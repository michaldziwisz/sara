"""Przerwy ze stołu: wspólny stan klientów, obsługiwany tylko w wątku wx."""

from __future__ import annotations

from sara.remote.main_playlist import main_panel


class HoldController:
    def __init__(self, frame) -> None:
        self.frame = frame
        self.enabled = False
        self.owned_breaks: set[tuple[str, str]] = set()
        self._playlist_id: str | None = None
        self._seen_playback = False

    def _entries(self, panel):
        if panel is None:
            return []
        return [(key, ctx) for key, ctx in self.frame._playback.contexts.items()
                if key[0] == panel.model.id and panel.model.get_item(key[1]) is not None]

    def sync(self) -> None:
        if not self.enabled:
            return
        panel = main_panel(self.frame)
        playlist_id = panel.model.id if panel else None
        if playlist_id != self._playlist_id:
            # Zmiana ustawienia/usunięcie głównej nie zostawia cudzej blokady.
            self._release_breaks()
            self._playlist_id = playlist_id
            self._seen_playback = False
        entries = self._entries(panel)
        if not entries:
            return
        self._seen_playback = True
        # Kolejność dodania kontekstów jest kolejnością startów. Podczas miksu
        # chronimy wchodzący, nie ucinamy schodzącego ani żadnego odtwarzacza.
        key, context = entries[-1]
        item = panel.model.get_item(key[1])
        if item.break_after:
            return  # Istniejąca ręczna przerwa nigdy nie staje się naszą.
        from sara.ui.controllers.playlists.hotkeys import toggle_playlist_breaks
        toggle_playlist_breaks(self.frame, panel, [panel.model.index_of(item.id)],
                               focus=False, announce=False, context_entry=(key, context))
        self.owned_breaks.add(key)

    def _release_breaks(self) -> None:
        from sara.ui.controllers.playlists.hotkeys import toggle_playlist_breaks
        for key in list(self.owned_breaks):
            panel = self.frame._playlists.get(key[0])
            item = panel.model.get_item(key[1]) if panel else None
            context = self.frame._playback.contexts.get(key)
            if item and item.break_after:
                if context is not None:
                    active_break = self.frame._active_break_item.get(key[0])
                    toggle_playlist_breaks(self.frame, panel, [panel.model.index_of(item.id)],
                                           focus=False, announce=False, context_entry=(key, context))
                    # Ctrl+B czyści znacznik playlisty. Stół nie jest właścicielem
                    # ręcznej przerwy na innym, wchodzącym utworze.
                    if active_break is not None and active_break != key[1]:
                        self.frame._active_break_item[key[0]] = active_break
                else:
                    # Zagrany utwór: tylko sprzątanie, bez planowania i startu.
                    item.break_after = False
                    self.frame._playback.auto_mix_state.pop(key, None)
                    if self.frame._active_break_item.get(key[0]) == key[1]:
                        self.frame._active_break_item.pop(key[0], None)
                    panel.update_item_display(item.id)
        self.owned_breaks.clear()

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            if not self.enabled:
                self._seen_playback = False
            self.enabled = True
            self.sync()
        else:
            self.enabled = False
            self._release_breaks()
            self._seen_playback = False
            self._playlist_id = None

    def response(self) -> str:
        panel = main_panel(self.frame)
        entries = self._entries(panel)
        if entries:
            state = "za_pozno" if self.enabled and len(entries) > 1 else "trzyma"
        elif self.enabled and self._seen_playback and panel and panel.model.break_resume_index is not None:
            state = "zatrzymane"
        else:
            state = "brak"
        return f"{int(self.enabled)},{state}"


def get_hold_controller(frame) -> HoldController:
    # Wywołanie dopiero z execute (GUI), nie z konstruktora sesji TCP
    # uruchamianego w wątku klienta.
    controller = getattr(frame, "_remote_hold", None)
    if controller is None:
        controller = frame._remote_hold = HoldController(frame)
    return controller
