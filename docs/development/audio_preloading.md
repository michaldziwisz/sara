# Preloading audio (miks bez opóźnień)

Na wolnych nośnikach (HDD, NAS, dyski sieciowe) uruchomienie kolejnego utworu potrafi mieć zauważalny lag (open/seek/prescan). W praktyce psuje to precyzję przejść w okolicy punktu miksu.

SARA ma mechanizm **preloadingu**, który próbuje przygotować „następny” utwór wcześniej – tak, aby w momencie miksu start był możliwie natychmiastowy.

## Jak to działa

Gdy startuje utwór z playlisty muzycznej, `PlaybackController` planuje preload kolejnego kandydata. Dotyczy to zarówno automiksu, jak i ręcznej kolejki zaznaczonych utworów. Zmiana zaznaczeń podczas odtwarzania przelicza kandydata bez zatrzymywania grającego utworu. Automiks uwzględnia także zawinięcie do pozycji już zagranych.

- **BASS backend**: tworzony jest osobny player i strumień BASS dla następnego utworu (`BassPlayer.preload`), bez odtwarzania. `PlaybackController` przechowuje tę instancję i przekazuje ją do startu na wybranym urządzeniu. Jest to istotne: `AudioEngine.create_player()` jest fabryką NOWEGO playera, a nie odczytem cache. Ponowne wywołanie fabryki przy miksie gubiło wcześniej wykonany preload.
- **Fallback (inne backendy / brak wsparcia)**: wykonywany jest „warm-up” systemowego cache pliku (`sara.core.file_prefetch.warm_file`) przez odczyt fragmentu danych.

Preloading jest best-effort. Powtórne zlecenie tej samej ścieżki, Cue, flagi pętli i urządzenia zachowuje już przygotowany strumień. Start używa go tylko po zakończeniu przygotowania. Zmiana pliku, Cue lub flagi pętli nadal przechodzi przez kontrolę zgodności w `BassPlayer._consume_preloaded`; zmiana urządzenia porzuca przygotowanego playera. Nie przesuwamy Cue i nie wyłączamy PRESCAN.

Nie ma oczekiwania na worker w ścieżce przekazania gotowego playera. Gdy przygotowanie nie zdążyło, nie udało się lub kandydat się zmienił, pozostaje dotychczasowe synchroniczne otwarcie. Nie jest to bezwarunkowa gwarancja startu poniżej 100 ms dla dowolnie wolnego nośnika ani wyboru zmienionego tuż przed miksem. Dla krótkiego intro potrzebny jest czas na wcześniejsze otwarcie następnego pliku.

## Własność zasobów i głośność

Kontroler przechowuje najwyżej jednego kandydata na playlistę. Osobny player przygotowania nie zastępuje grającego ani PFL w cache silnika. Porzucone zlecenie jest anulowane, jeśli jeszcze nie wystartowało; zwolnienie strumienia odbywa się w tym samym pojedynczym executorze po ewentualnym trwającym otwarciu. Stop, usunięcie playlisty i zamknięcie okna zwalniają przygotowanie bez czekania w GUI.

Automat EBU chroni także ścieżki przechowywane przez kontroler, zanim i po tym jak backend opublikuje gotowy uchwyt. Bariera zadań obejmuje sprzątanie. Wzmocnienie grającego lub przygotowanego strumienia nie jest zmieniane przez wynik pomiaru. Przy właściwym starcie pozostaje dotychczasowe ustawienie ReplayGain. Kod silnika BASS, punkty pętli, wyzwalacze, PFL i fade nie zostały zmienione.

## Diagnostyka przygotowania

Dziennik DEBUG rozróżnia `Preload scheduled`, `Preload finished` (wynik i czas), `Preload handed off`, `Preload miss`, `Preload discarded` i fallback `Preload file warmup`. Brak wpisów w starszej wersji nie dowodził braku pracy: udany preload w ogóle nie był logowany.

Regresje integracyjne są w `tests/test_playback_preload_handoff.py`: rzeczywista fabryka `AudioEngine`, rzeczywisty `BassPlayer` i atrapa wolnego otwarcia (120 ms). Sprawdzają ręczną kolejkę, automiks, zawijanie, przekazanie tej samej instancji, zmianę kandydata, niegotowe zlecenie, zatrzymanie i zamknięcie oraz zachowanie Cue, pętli i gainu. `scripts/check_remote_mutations.py` zawiera mutanty gubienia playera, pomijania ręcznej kolejki i zapisu EBU do przygotowanego pliku.

### Pomiar Windows, 25.10.2026

Dla MP3 95 661 947 bajtów zmierzono na BASS w trybie `STREAM_DECODE`, z urządzeniem 0 i priorytetem BELOW_NORMAL:

- `StreamCreateFile` z PRESCAN: pierwsze otwarcie 173,87 ms (stan cache nieznany), kolejne 207,53 i 222,74 ms. Bez PRESCAN: 0,34 i 1,45 ms. Nie usuwamy PRESCAN, bo szybkie otwarcie nie jest gwarancją dokładnego pozycjonowania wszystkich plików.
- Kontrola z odczytem pliku przez `FILE_FLAG_NO_BUFFERING` i `StreamCreateFileUser`: PRESCAN 4493,11 ms; bez niego 16,76 ms. To ominięcie cache plikowego Windows, nie dowód zimnego cache sprzętowego dysku. Nie czyszczono pamięci systemu ani nie restartowano komputera.
- Natywny wyzwalacz intro → wpis `playback started`: przed zmianą 158,13–167,76 ms przy zwykłym odczycie i 4326,68–4483,65 ms w kontroli niebuforowanej; po zmianie odpowiednio 0,45–0,46 ms oraz 0,51–0,68 ms. Dwie próby każdej kombinacji, przygotowanie w tle przed wyzwalaczem. Pętla 0..3413,235 s nadal ma koniec 602 094 652 bajty PCM. Skróty porównanych próbek przy Cue, pozycji 9,111 s i 100,125 s oraz po natywnym zawinięciu są zgodne przed i po zmianie.

Pomiar korzysta z rzeczywistych funkcji startu UI i kontrolera, ale nie otwiera urządzeń wyjściowych: `ChannelPlay` zastępuje pobranie pierwszego bloku PCM. Callback natywny wywołuje start bez kolejki zdarzeń wx. Wynik nie obejmuje opóźnień sterownika, akustyki ani zajętego GUI. Odsłuch antenowy i PFL na żywym stanowisku pozostają osobnym odbiorem. Skrypty i surowe wyniki: `.venv/tmp/sara-lag/` (nie są częścią aplikacji).

## PFL / podsłuch miksu

Podgląd miksu na PFL (`start_mix_preview`) również próbuje przygotować utwór B przed punktem miksu, żeby odsłuch przejścia był możliwie 1:1 z emisją (bez dodatkowego laga na starcie B).

PFL i emisja muszą uzbrajać punkty miksu tą samą ścieżką: jeśli backend obsługuje natywny trigger, `mix_trigger_seconds` i callback są przekazywane już do `player.play(...)`, tak aby backend mógł uzbroić trigger przed startem strumienia. Nie należy dopinać triggera dopiero po rozpoczęciu odtwarzania, bo to wprowadza inną oś czasu niż na emisji.

Okno podglądu (od kiedy startuje utwór A i z jakim opóźnieniem wpada B) liczy wspólna, czysta funkcja `mix_planner.preview_window(mix_at, pre_seconds)` — to samo źródło prawdy dla wszystkich podglądów.

## Diagnostyka PFL vs emisja

Przy podglądzie miksu PFL logi `PFL mix preview` zapisują:

- uzbrojenie triggera (`arming trigger`) z `native`, `mix_at`, `start_a`, `delay` i urządzeniem PFL,
- faktyczne odpalenie B (`fire`) z `source=native|timer|immediate`, pozycją playera A (`a_pos`) i punktem startu B (`next_start`),
- start B (`next started`) oraz ewentualne pominięcie timera fallback, jeśli natywny trigger zdążył już odpalić miks.

PFL ma DOKŁADNIE jedną ścieżkę wyzwalania: natywny callback (mixtime) jest autorytetem i odpala miks od razu; timer fallback działa tylko gdy backend nie obsługuje natywnego triggera albo native nie odpalił w oknie `delay + guard`. Nie ma już odraczania „native trigger early -> position wait" — porównywanie natywnego mixtime z `get_position` (osią odtwarzania, opóźnioną o bufor) wprowadzało niedeterminizm. Szczegóły modelu: `docs/development/deterministic_mix_loop.md`.

Dzięki temu log PFL można porównać z logami BASS emisji (`BASS mix trigger set/fired`) bez zgadywania, czy przejście było zrobione przez natywny trigger czy awaryjny timer.

## Konfiguracja (env)

- `SARA_ENABLE_PRELOAD` (domyślnie `1`) – wyłącz: `0`.
- `SARA_PRELOAD_WARM_BYTES` (domyślnie `33554432`, czyli 32 MiB) – ile danych czyta fallback warm-up.
- `SARA_PRELOAD_REFETCH_SECONDS` (domyślnie `60`) – minimalny odstęp między kolejnymi warm-up tego samego pliku.
- `SARA_BASS_ASYNCFILE` (domyślnie `1`) – dodaje flagę `BASS_ASYNCFILE` do `BASS_StreamCreateFile`, co pomaga na wolnych I/O.
- `SARA_BASS_BUFFER_MS` (domyślnie `250`) – ustawia długość bufora wyjściowego BASS (mniejsze wartości = mniejsza latencja i mniej „rozjazdów” przy `SYNC_MIXTIME`, ale zbyt niskie mogą powodować dropy).

## Kod

- Preload planowanie: `src/sara/ui/playback/controller.py` (`schedule_next_preload`).
- PFL mix preview: `src/sara/ui/playback/preview.py` (`start_mix_preview`).
- Warm-up: `src/sara/core/file_prefetch.py` (`warm_file`).
- BASS preload + użycie przygotowanego strumienia: `src/sara/audio/bass/player/base.py`, `src/sara/audio/bass/player/flow.py`.
