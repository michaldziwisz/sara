# Preloading audio (miks bez opóźnień)

Na wolnych nośnikach (HDD, NAS, dyski sieciowe) uruchomienie kolejnego utworu potrafi mieć zauważalny lag (open/seek/prescan). W praktyce psuje to precyzję przejść w okolicy punktu miksu.

SARA ma mechanizm **preloadingu**, który próbuje przygotować „następny” utwór wcześniej – tak, aby w momencie miksu start był możliwie natychmiastowy.

## Jak to działa

Gdy automix jest włączony i startuje utwór, `PlaybackController` planuje preload kolejnego kandydata:

- **BASS backend**: tworzony jest strumień BASS dla następnego utworu (`BassPlayer.preload`) i trzymany w obiekcie playera (bez odtwarzania). Przy właściwym `play()` player próbuje użyć przygotowanego strumienia zamiast otwierać plik od zera.
- **Fallback (inne backendy / brak wsparcia)**: wykonywany jest „warm-up” systemowego cache pliku (`sara.core.file_prefetch.warm_file`) przez odczyt fragmentu danych.

Preloading jest best-effort: jeśli kolejny utwór się zmieni (np. ręczny wybór), przygotowany preload zostanie porzucony.

## PFL / podsłuch miksu

Podgląd miksu na PFL (`start_mix_preview`) również próbuje przygotować utwór B przed punktem miksu, żeby odsłuch przejścia był możliwie 1:1 z emisją (bez dodatkowego laga na starcie B).

PFL i emisja muszą uzbrajać punkty miksu tą samą ścieżką: jeśli backend obsługuje natywny trigger, `mix_trigger_seconds` i callback są przekazywane już do `player.play(...)`, tak aby backend mógł uzbroić trigger przed startem strumienia. Nie należy dopinać triggera dopiero po rozpoczęciu odtwarzania, bo to wprowadza inną oś czasu niż na emisji.

Runtime miksu może odczytać bieżącą pozycję z backendu (`get_position_seconds()`), żeby zabezpieczyć się przed dryftem wynikającym z opóźnionych callbacków postępu UI.

## Diagnostyka PFL vs emisja

Przy podglądzie miksu PFL logi `PFL mix preview` zapisują:

- uzbrojenie triggera (`arming trigger`) z `native`, `mix_at`, `start_a`, `delay` i urządzeniem PFL,
- faktyczne odpalenie B (`fire`) z `source=native|timer|immediate`, pozycją playera A (`a_pos`) i punktem startu B (`next_start`),
- start B (`next started`) oraz ewentualne pominięcie timera fallback, jeśli natywny trigger zdążył już odpalić miks.

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
