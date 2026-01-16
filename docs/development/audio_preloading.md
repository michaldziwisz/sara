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
