# Plan refaktoryzacji SARA (bez zmian funkcjonalnych)

Ten dokument opisuje bezpieczny, iteracyjny plan uporządkowania kodu SARA. Celem jest zmniejszenie rozmiaru największych plików, rozdzielenie odpowiedzialności oraz poprawa testowalności – bez zmiany zachowania aplikacji.

## Status (gałąź refaktorowa)

- `src/sara/ui/main_frame.py` został odchudzony do ~900 linii i stał się głównie „fasadą” delegującą do mniejszych modułów.
- Logika miksowania jest wydzielona do `src/sara/core/mix_planner.py` oraz `src/sara/ui/mix_runtime.py` (testy miksu nie wymagają już importowania `MainFrame`).
- Większość „UI glue” została przeniesiona do `src/sara/ui/controllers/…` (playback flow, automix, skróty, schowek/undo, import/export playlist, folder playlists, news audio).
- Panele UI zostały pogrupowane w `src/sara/ui/panels/…` (kompatybilne fasady importów pozostają w `src/sara/ui/*_playlist_panel.py` i `src/sara/ui/playlist_panel.py`).
- `sara/audio` zostało rozbite na mniejsze moduły (utrzymując publiczne API przez fasady):
  - `src/sara/audio/bass/…` zawiera implementację BASS (native/manager/backends/player), a kompatybilne fasady importów są utrzymane w `src/sara/audio/bass_player.py` oraz `src/sara/audio/bass_*.py`.
  - `src/sara/audio/mixer/__init__.py` eksportuje API mixera, a implementacja jest poukładana w `src/sara/audio/mixer/…` (device/stream, DSP, render, lifecycle, wątek, manager, player).
    - Kompatybilne importy: `src/sara/audio/device_mixer.py` i `src/sara/audio/mixer_player.py` są fasadami wskazującymi na `sara.audio.mixer`.
  - `src/sara/audio/sounddevice/…` zawiera implementację sounddevice, a `src/sara/audio/sounddevice_player.py`, `src/sara/audio/sounddevice_provider.py`, `src/sara/audio/sounddevice_player_base.py` i `src/sara/audio/sounddevice_profiles.py` są fasadami kompatybilności.
  - Wspólne elementy audio są wydzielone do `src/sara/audio/types.py`, `src/sara/audio/resampling.py` i `src/sara/audio/transcoding.py`.

## Diagnoza (największe punkty bólu)

- `src/sara/ui/main_frame.py` historycznie (~4.6k linii) łączył wiele odpowiedzialności: UI, skróty, I/O playlist, logikę automix, planowanie miksu, schowek, undo, alerty, zarządzanie playlistami.
- Historycznie część testów miksu zależała od `MainFrame` (i przez to od `wx`), ale ten kierunek refaktoru zakłada przepięcie testów na moduły `core/ui` (np. `tests/test_mix_triggers.py` nie importuje już `sara.ui.main_frame`).
- W repozytorium występują drobne „techniczne” duplikaty (np. podwójne definicje metod), które utrudniają refaktor i czytanie kodu.

## Zasady bezpieczeństwa (żeby nie „rozwalić” kodu)

1. **Małe kroki + testy po każdym kroku**: po każdej zmianie uruchamiaj `PYTHONPATH=src venv_codex/bin/python -m pytest`.
2. **Nie łącz przenosin z logiką**: najpierw przeniesienie/ekstrakcja (z wrapperami), dopiero potem ewentualne uproszczenia.
3. **Kompatybilność importów**: dopóki to możliwe, zachowuj istniejące ścieżki importów (szczególnie `sara.ui.main_frame:MainFrame`).
4. **Kompozycja zamiast dziedziczenia**: `MainFrame` ma być „orchestratorem” i delegować do mniejszych komponentów.
5. **Brak zależności `core` od `ui`**: logika biznesowa/testowalna w `sara/core` nie importuje `wx`.
6. **Refaktor z adapterami**: nowe klasy/funkcje wprowadzaj w sposób, który pozwala na stopniowe przepinanie wywołań.

## Cel docelowy (wysoki poziom)

- `sara/core`: czysta logika i modele (bez `wx`).
- `sara/audio`: backendy i miksowanie (bez zależności od UI).
- `sara/ui`: okna/dialogi, binding eventów, dostępność; minimalna logika „biznesowa”.

W praktyce oznacza to:
- wydzielenie „plannerów/serwisów” do `core`,
- wydzielenie kontrolerów UI do osobnych modułów,
- redukcję `main_frame.py` do roli integratora.

## Plan etapów (kolejność i kryteria akceptacji)

### Etap 0 — Ustalenie baseline i higiena

- Upewnić się, że testy przechodzą w środowisku roboczym.
- Naprawić techniczne duplikaty (bez zmiany API/behavior).

**Akceptacja:** `pytest` zielone, brak zmian funkcjonalnych.

### Etap 1 — Wydzielenie logiki miksu z `MainFrame` do `core`

Cel: testy miksu nie powinny wymagać importowania `wx` i `MainFrame`.

Propozycja:
- nowy moduł `src/sara/core/mix_planner.py` (nazwy do doprecyzowania),
- przeniesienie tam:
  - `MixPlan` (lub rozdzielenie na DTO + funkcje),
  - obliczenia typu `resolve_mix_timing`, `compute_mix_trigger_seconds`, rejestracja/aktualizacja planów.
- `MainFrame` staje się klientem planner’a (deleguje, trzyma jedynie stan UI).
- Testy `tests/test_mix_triggers.py` przepinamy na `sara.core.mix_planner`.

**Akceptacja:** `pytest` zielone, `tests/test_mix_triggers.py` nie importuje `sara.ui.main_frame`.

### Etap 2 — Rozbicie dialogów/okien z końca `main_frame.py`

Najbezpieczniejszy „odchudzacz”:
- przeniesienie `ManagePlaylistsDialog` do osobnego pliku w `sara/ui` (np. `sara/ui/manage_playlists_dialog.py` lub `sara/ui/dialogs/manage_playlists.py`),
- pozostawienie w `main_frame.py` importu i brak zmian zachowania.

**Akceptacja:** `pytest` zielone, brak zmian UI.

### Etap 3 — Wydzielenie I/O playlist (import/export, m3u, tworzenie itemów)

Cel: `main_frame.py` nie powinien zawierać logiki parsowania i budowania elementów playlist.

Propozycja:
- moduł `sara/core/playlist_io.py` (czyste parsowanie M3U / serializacja),
- moduł `sara/ui/playlist_importer.py` (obsługa dialogów i integracja z UI).

**Akceptacja:** `pytest` zielone, import/export działa jak wcześniej.

### Etap 4 — Wydzielenie „edycji playlist” (schowek + undo + move/delete)

Cel: skupienie operacji edycyjnych w jednym komponencie.

Propozycja:
- `sara/ui/edit_controller.py` lub `sara/ui/playlist_editing.py`,
- `MainFrame` zawiera tylko binding eventów i wywołania komponentu.

**Akceptacja:** `pytest` zielone, operacje edycyjne bez regresji.

### Etap 5 — Porządek w `MainFrame`: podział na regiony i moduły pomocnicze

Po wydzieleniach powyżej `main_frame.py` powinien spaść do „rozsądnego” rozmiaru i mieć czytelne sekcje.

Propozycja:
- wydzielenie kontrolerów: `AutoMixController`, `AnnouncementController`, `HotkeyController` (nazwy do ustalenia),
- dopiero na końcu rozważenie opakowania `main_frame.py` jako „fasady” (opcjonalnie).

**Akceptacja:** `pytest` zielone, brak zmian API importów.

### Etap 6 — Porządek w `sara/audio`: backendy i mixer

Cel: utrzymać małe, czytelne moduły audio, bez mieszania z UI oraz bez rozbijania publicznego API.

Propozycja:
- utrzymywać „fasady” jako stabilne punkty importów (`sara.audio.bass`, `sara.audio.bass_player`, `sara.audio.mixer`, `sara.audio.sounddevice_backend`, `sara.audio.sounddevice_player`),
- dalej rozbijać duże implementacje wewnętrzne (np. `sounddevice/player_base.py`, `device_mixer.py`) przez wyciąganie typów i helperów,
- dążyć do tego, żeby moduły audio nie importowały `sara.audio.engine` (używać `sara.audio.types` + `sara.audio.resampling`).

**Akceptacja:** `pytest` zielone, brak zmian zachowania audio.

## Strategia pracy na Gicie

- Osobny branch na cały refaktor (`refactor/...`) oraz opcjonalnie mniejsze branche per etap (łatwiejszy review).
- Częste commity o małym zakresie (np. „extract mix planner”, „move dialog”).
- W razie potrzeby: `git mv` przy przenoszeniu plików.

## Ryzyka i jak je ograniczamy

- **Duże przenosiny**: minimalizujemy przez wrappery/re-exporty i iteracyjne przepinanie wywołań.
- **Cykle importów**: nowa logika w `core` nie importuje `ui`; zależność tylko w jedną stronę.
- **Testy zależne od implementacji**: w miarę przenosin przekierowujemy testy na API modułów „core”.

## Otwarte decyzje (pytania)

1. Preferujesz nazewnictwo nowych modułów po angielsku czy po polsku (np. `mix_planner` vs. `planer_miksu`)?
2. Czy dopuszczamy stworzenie podpakietu `sara/ui/dialogs/…`, czy trzymamy wszystko płasko w `sara/ui/`?
3. Czy w dłuższej perspektywie dopuszczasz, aby `sara.ui.main_frame` stał się cienką fasadą importującą właściwą implementację z innego modułu (bez zmiany ścieżki importu)?
