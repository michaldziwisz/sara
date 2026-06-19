# Plan: powtarzalne pętle i miksy wg zadanych punktów

> **Dla Hermesa:** plan do wykonania zadanie-po-zadaniu. Każde zadanie =
> jeden plik / jedna zmiana, izolacja zmiennej, TDD, osobny commit.

**Cel:** Wyeliminować niedeterminizm odtwarzania pętli i miksów. Ten sam utwór
z tymi samymi punktami (loop start/end, segue/overlap/fade, cue-in) ma ZAWSZE
dać identyczny efekt słyszalny — bez „rozjeżdżania się" zależnego od obciążenia
CPU czy kolejności wątków.

**Zasada nadrzędna (wymóg Michała):** minimalna ingerencja. Poprawiając timing
miksu/pętli NIE ruszamy działających mechanizmów (urządzenia audio, ASIO,
ReplayGain, news, jingle). Jeden plik = jedna zmiana, czytelnie nazwana.

**Diagnoza (źródło problemu):** opisana w sekcji „Analiza" niżej. Plan adresuje
pięć przyczyn: (A) wyścig wielu ścieżek wyzwalania, (B) niespójne progi/guardy,
(C) podwójne zawijanie pętli (native + python guard), (D) fade na zegarze
ściennym, (E) kumulacja błędów float zamiast jednego źródła prawdy w bajtach.

---

## Analiza obecnego stanu (kontekst dla implementującego)

Główne pliki:
- `src/sara/audio/bass/player/base.py` — rdzeń BassPlayer: pętla (native loop
  points + fallback marker-sync), arming miksu, stan.
- `src/sara/audio/bass/player/mix_trigger.py` — natywny wyzwalacz miksu
  (SYNC_POS mixtime + SYNC_END fallback), `_invoke_once` z `_mix_triggered`.
- `src/sara/audio/bass/player/flow.py` — `play`, `stop`, `jump_to_loop_start`,
  `fade_out` (wątek na `time.sleep`).
- `src/sara/audio/bass/player_monitor.py` — wątek monitorujący (interwał
  0.001 s): progress callback, strażnik pętli (guard/clamp), restart po końcu.
- `src/sara/audio/bass/_manager/streams.py` — natywne wywołania BASS
  (set_loop_points przez POS_LOOP/POS_END, sync pos/end, seconds_to_bytes).
- `src/sara/audio/bass/manager.py` — konfiguracja BASS (BUFFER 250 ms,
  UPDATEPERIOD 1 ms, UPDATETHREADS 4).
- `src/sara/core/mix_planner.py` — czysta logika timingu (testowalna bez wx):
  `resolve_mix_timing`, guardy MIX_NATIVE_EARLY/LATE, MIX_EXPLICIT_PROGRESS.
- `src/sara/ui/mix_runtime/now.py` — automix natychmiastowy (z natywnego
  callbacku), z fallbackiem „backend fired early -> progress trigger".
- `src/sara/ui/mix_runtime/progress.py` — automix oparty o progres (gdy brak
  natywnego wyzwalacza lub jako siatka bezpieczeństwa).
- `src/sara/ui/mix_runtime/triggers.py` — rejestracja/aktualizacja planu miksu.
- `src/sara/ui/playback/preview.py` — PFL: `start_mix_preview` z PIĘCIOMA
  ścieżkami odpalenia (native, native_wait, native_wait_timeout, timer,
  immediate) + `start_preview`/`update_loop_preview`.

Pięć źródeł niedeterminizmu:

(A) WYŚCIG WYZWALACZY. Punkt miksu może odpalić: natywny SYNC_POS, natywny
SYNC_END (fallback), pythonowy monitor progresu, fallback w `now.py`. W PFL aż
pięć dróg. Zwycięzca zależy od schedulera OS → różny efekt przy tych samych
danych. Istnieje `_mix_triggered`/`fired_event`, ale guardy PRZED nim
(`MIX_NATIVE_EARLY_GUARD` w `now.py`, „native position wait" w preview) potrafią
ODŁOŻYĆ albo PRZESUNĄĆ realny moment, więc „kto pierwszy" wciąż zmienia wynik.

(B) NIESPÓJNE PROGI. `MIX_NATIVE_EARLY_GUARD=0.25`, `MIX_NATIVE_LATE_GUARD=0.35`,
`MIX_EXPLICIT_PROGRESS_GUARD=0.05`. `progress.py` liczy `release_offset`,
`guard_window`, `late_guard_shortfall` — efektywny punkt miksu zależy od tego,
która gałąź guardu się uaktywni. Trudne do przewidzenia i powtórzenia.

(C) PODWÓJNE ZAWIJANIE PĘTLI. Gdy `_loop_native_active=True` (BASS zawija
sam, próbka-w-próbkę, w mixtime), monitor w `player_monitor.py` i tak liczy
`pos > loop_end + guard_slack` i robi własny `channel_set_position`. To drugi,
software'owy mechanizm zawijania działający równolegle do natywnego → ryzyko
podwójnego skoku, kliknięcia, mikro-dryfu. Guard miał być siatką awaryjną dla
trybu fallback (bez native), a działa też przy native.

(D) FADE NA ZEGARZE ŚCIENNYM. `fade_out` w `flow.py`: pętla kroków co
`time.sleep(duration/steps)`. Pod obciążeniem realny czas i kształt krzywej
pływają → wyciszenie nie jest powtarzalne, a koniec fade (a więc i `stop` +
`finished_callback`) wypada w różnych momentach.

(E) BŁĘDY FLOAT. Timing liczony w sekundach z wielokrotnym dodawaniem
(`base_cue + segue`, minus `start_offset`, konwersja s→bajty w wielu miejscach).
Pętla ma już bajty (`_loop_start_bytes`), ale miks i fade — nie. Jedno źródło
prawdy w bajtach (próbkach) usuwa dryf zaokrągleń.

Konfiguracja BASS: BUFFER 250 ms. Przy `SYNC_MIXTIME` callback odpala w punkcie
miksowania (z wyprzedzeniem bufora względem słyszalnego dźwięku), a
`ChannelGetPosition` zwraca pozycję ODTWARZANĄ (po buforze). To znaczy: native
mixtime sync jest spójny sam ze sobą, ale porównywanie go z `get_position`
(co robią guardy w `now.py`/preview) MIESZA dwie osie czasu → pozorne
„fired early" i niepotrzebne przełączanie na fallback. To sedno (A)+(B).

---

## Podejście (strategia)

Zamiast dokładać kolejne guardy — UPROŚCIĆ do JEDNEJ autorytatywnej ścieżki
wyzwalania na każdą funkcję, z deterministycznym fallbackiem tylko gdy native
jest niedostępny. Punkty liczyć raz, w bajtach, i przekazywać w dół. Pętlę
zawijać jednym mechanizmem. Fade oprzeć na pozycji strumienia, nie na zegarze.

Każda zmiana ma być w pełni pokryta testem na stubie managera (jak istniejące
`tests/test_bass_player.py` i `tests/test_mix_triggers.py`) — bez realnego BASS.

Kolejność: najpierw rzeczy najłatwiej izolowalne i najbezpieczniejsze
(diagnostyka + pętla), potem miks, na końcu PFL i fade.

---

## Faza 0 — siatka bezpieczeństwa (testy charakteryzujące)

### Zadanie 0.1: Test charakteryzujący determinizm wyzwalacza miksu

**Cel:** Zafiksować obecny *poprawny* kontrakt zanim cokolwiek ruszymy, by
refaktor niczego nie zmienił poza usunięciem niedeterminizmu.

**Pliki:**
- Test: `tests/test_mix_trigger_determinism.py` (nowy)

**Krok 1:** Napisz test, który dla `_StubManager` (wzór z
`tests/test_bass_player.py`) wywołuje `_apply_mix_trigger(target, cb)` i
sprawdza, że:
- przy `start_offset>0` target w bajtach = `(target-offset)*1000` (już jest),
- callback odpala DOKŁADNIE raz niezależnie od kolejności `last_pos_proc` i
  `last_end_proc` (już jest w `test_bass_mix_trigger_fires_once_for_pos_and_end`
  — rozszerz o odwrotną kolejność: end PRZED pos).

**Krok 2:** Uruchom: `python3 -m pytest tests/test_mix_trigger_determinism.py -v`
Oczekiwane: PASS (charakteryzuje istniejące zachowanie).

**Krok 3:** Commit.
```
git add tests/test_mix_trigger_determinism.py
git commit -m "test(playback): characterize mix trigger fire-once contract"
```

---

## Faza 1 — pętla: jeden mechanizm zawijania (przyczyna C)

### Zadanie 1.1: Wyłącz pythonowy guard pętli, gdy aktywna pętla natywna

**Cel:** Gdy `_loop_native_active=True`, BASS zawija sam — pythonowy guard
(`pos > loop_end + slack` → `jump_to_loop_start`) ma NIE działać. Guard zostaje
WYŁĄCZNIE jako fallback dla trybu marker-sync (gdy native niedostępny).

**Pliki:**
- Modyfikacja: `src/sara/audio/bass/player_monitor.py` (warunek strażnika ~l. 49-80)
- Test: `tests/test_bass_player.py` (dopisz przypadek)

**Krok 1 (test RED):** Dopisz test: player z `native_loop_supported=True`,
`set_loop(...)`, ustaw `current_byte_position` powyżej `loop_end_bytes`, wywołaj
jeden cykl logiki strażnika (wydziel ją do funkcji testowalnej — patrz krok 2)
i sprawdź, że NIE wykonano `channel_set_position_bytes` (bo native zawija).
Drugi test: `native_loop_supported=False` → guard NADAL skacze.

**Krok 2 (implementacja):** W warunku strażnika dodaj
`and not player._loop_native_active`. Czyli:
```python
if (
    player._loop_guard_enabled
    and loop_active
    and not player._loop_native_active   # native sam zawija, guard tylko dla fallbacku
    and loop_end is not None
    and loop_start is not None
):
```
Pozostaw twardy clamp (`pos > loop_end + 0.05`) jako absolutną awarię TYLKO dla
fallbacku (też pod `not _loop_native_active`). Restart po `not active` zostaje
bez zmian (dotyczy obu trybów).

**Krok 3:** `python3 -m pytest tests/test_bass_player.py -v` → PASS.

**Krok 4:** Commit `fix(loop): let native loop wrap without python guard`.

### Zadanie 1.2: Spójny clamp punktu końca pętli do długości i do startu

**Cel:** `_apply_loop_settings` już robi `end = max(start+0.001, loop_end)`.
Dodaj clamp do długości strumienia, by `end` nigdy nie przekraczał materiału
(inaczej native loop end wypada poza plik → BASS ignoruje pętlę lub zawija
chaotycznie).

**Pliki:**
- Modyfikacja: `src/sara/audio/bass/player/base.py` `_apply_loop_settings` (~l. 388-395)
- Test: `tests/test_bass_player.py`

**Krok 1 (test):** stub z `channel_get_length_seconds` mniejszym niż `loop_end`
→ po `set_loop` `_loop_end_bytes` odpowiada długości - epsilon, nie wartości
zadanej.

**Krok 2:** Po obliczeniu `end` dodaj clamp do długości (jeśli manager zwraca
length>0): `end = min(end, length_seconds - 0.001)` i ponów `max(start+0.001,...)`.

**Krok 3:** test PASS. Commit `fix(loop): clamp loop end to stream length`.

---

## Faza 2 — miks emisji: jedna autorytatywna ścieżka (przyczyny A, B, E)

### Zadanie 2.1: Ujednolić oś czasu — guardy w now.py liczone w osi mixtime

**Cel:** Usunąć fałszywe „backend fired early". Gdy native sync (mixtime)
odpala, NIE porównujemy z `get_position_seconds` (oś odtwarzania, opóźniona o
bufor). Native sync = autorytet; jeśli odpalił, miks następuje. `get_position`
używamy tylko gdy native NIE jest źródłem (fallback progresowy).

**Pliki:**
- Modyfikacja: `src/sara/ui/mix_runtime/now.py` (blok `current_abs < expected_mix - tolerance`, l. 110-156)
- Test: `tests/test_mix_triggers.py` (rozszerz `_MixHost`)

**Krok 1 (test):** scenariusz: native_trigger=True, callback z BASS odpala gdy
`get_position` jeszcze pokazuje wartość mniejszą od `mix_at` o ~bufor (np.
mix_at=9.0, backend_pos=8.8 przy buforze 0.25). Oczekiwane PO zmianie: miks
NASTĘPUJE (nie przełącza na fallback), bo native to mixtime.

**Krok 2 (implementacja):** Wprowadź rozróżnienie: jeśli `plan.native_trigger`
i wywołanie pochodzi z natywnego callbacku → pomiń sprawdzenie
`current_abs < expected_mix - MIX_NATIVE_EARLY_GUARD` (to ono powoduje zbędny
fallback). Najczyściej: dodaj do `auto_mix_now` parametr `source: str = "native"`
i przekazuj go z `auto_mix_now_from_callback`. Dla `source=="native"` ufamy
wyzwalaczowi. Fallback early-guard zostaje tylko dla wejść nie-natywnych
(np. ręczny automix z UI bez planu).

**Krok 3:** test PASS + istniejące testy now.py PASS.

**Krok 4:** Commit `fix(mix): trust native mixtime trigger, drop false early fallback`.

### Zadanie 2.2: Skonsolidować guardy progress.py do jednego progu

**Cel:** Zredukować `release_offset`/`guard_window`/`late_guard_shortfall` do
jednej przewidywalnej reguły: progres jest SIATKĄ BEZPIECZEŃSTWA pod native
(odpala tylko gdy native zawiódł, blisko końca), albo GŁÓWNĄ ścieżką gdy brak
native. Bez native: trigger gdy `remaining_target <= MIX_EXPLICIT_PROGRESS_GUARD`.
Z native: progres NIE odpala przed `mix_at` (zostawia to native), a po `mix_at`
+ małym oknie awaryjnym (np. 1 krok monitora) odpala dopiero gdy native ewidentnie
nie zadziałał.

**Pliki:**
- Modyfikacja: `src/sara/ui/mix_runtime/progress.py` (l. 76-118)
- Test: `tests/test_mix_triggers.py`

**Krok 1 (test):** trzy scenariusze:
- brak native, `seconds=mix_at-0.04` → trigger (guard 0.05).
- native, `seconds` między `mix_at-EARLY` a `mix_at` → NIE trigger (czeka na native).
- native zawiódł, `seconds > mix_at + okno_awaryjne` → trigger awaryjny.

**Krok 2 (implementacja):** zastąp wieloczłonowy blok release_offset prostą
logiką jak wyżej. Stałą okna awaryjnego dodaj do `mix_planner.py`
(`MIX_NATIVE_SAFETY_NET = 0.20`) — jeden jawny próg zamiast wyliczeń.

**Krok 3:** wszystkie testy mix PASS. Commit
`refactor(mix): single safety-net guard for progress automix`.

### Zadanie 2.3: Przenieść punkt miksu do bajtów (przyczyna E)

**Cel:** `mix_trigger.py` już konwertuje na bajty raz (`target_bytes`) i ustawia
SYNC_POS w bajtach — to dobrze. Upewnić się, że plan UI (`mix_at` w sekundach)
i backend używają TEJ SAMEJ konwersji (manager.seconds_to_bytes), oraz że
clamp `length-0.01` jest liczony w bajtach, nie dwukrotnie w sekundach.

**Pliki:**
- Modyfikacja: `src/sara/audio/bass/player/mix_trigger.py` (l. 27-33)
- Test: `tests/test_bass_player.py`

**Krok 1 (test):** sprawdź, że dla `target` blisko końca clamp daje
`seconds_to_bytes(length-0.01)` a nie `seconds_to_bytes(target)`; że
przy `start_offset` odejmowanie zachodzi RAZ.

**Krok 2:** drobne porządki — jeśli logika już poprawna, test tylko ją fiksuje
(test charakteryzujący). Nie ruszać jeśli zielone.

**Krok 3:** Commit `test(mix): pin byte-domain mix target conversion` (lub fix).

---

## Faza 3 — PFL: redukcja pięciu ścieżek do jednej (przyczyna A)

### Zadanie 3.1: Jedna ścieżka odpalenia PFL z deterministycznym fallbackiem

**Cel:** `start_mix_preview` ma odpalać przez DOKŁADNIE jeden mechanizm:
- jeśli `supports_native_trigger`: native callback `_fire_mix("native")` jest
  autorytetem; timer fallback służy WYŁĄCZNIE gdy native nie odpalił w
  `delay_b + guard` (już jest `fired_event` — dobrze). USUNĄĆ pośrednią ścieżkę
  „native_wait"/„native_wait_timeout" (`_schedule_native_position_wait`), bo to
  ona porównuje pozycję odtwarzaną z mix_at i wprowadza wariację. Native w PFL
  to ten sam mixtime sync co w emisji — ufamy mu.
- jeśli brak native: tylko timer (`delay_b`) — czysty, jeden wątek.

**Pliki:**
- Modyfikacja: `src/sara/ui/playback/preview.py` `start_mix_preview`
  (usuń `_schedule_native_position_wait` i gałąź `pos_a < mix_at - EARLY` w
  `_fire_mix`; l. 281-354)
- Test: `tests/test_pfl_mix_preview_preloading.py`

**Krok 1 (test):** native odpala → B startuje raz, fade raz, timer pomija się
(`already_fired`). Native NIE odpala → timer odpala po `delay_b`. Brak ścieżki
native_wait w logach/zachowaniu.

**Krok 2 (implementacja):** zredukuj `_fire_mix` do: stop/already_fired guard →
`fired_event.set()` → start B → fade A. Bez odraczania. Zachowaj `source` do
logu.

**Krok 3:** testy PFL PASS. Commit
`refactor(pfl): single mix-preview trigger path, drop position-wait race`.

### Zadanie 3.2: Wyrównać PFL i emisję do wspólnej funkcji liczenia delay

**Cel:** `delay_b = mix_at - start_a` i `start_a = mix_at - pre_seconds` liczone
lokalnie. Wyciągnąć do `mix_planner.py` (czysta, testowalna) wspólną funkcję
`preview_window(mix_at, pre_seconds)` → `(start_a, delay_b)` z clampem do zera,
by PFL i ewentualne inne podglądy używały tej samej matematyki.

**Pliki:**
- Modyfikacja: `src/sara/core/mix_planner.py` (nowa funkcja)
- Modyfikacja: `src/sara/ui/playback/preview.py` (użycie)
- Test: `tests/test_mix_triggers.py`

**Krok 1-3:** test funkcji, podmiana, PASS, commit
`refactor(pfl): share preview-window math via mix_planner`.

---

## Faza 4 — fade powtarzalny (przyczyna D)

### Zadanie 4.1: Fade sterowany pozycją strumienia, nie zegarem ściennym

**Cel:** Krzywa wyciszenia ma zależeć od POZYCJI odtwarzania (próbek), nie od
`time.sleep`. Pod obciążeniem CPU fade ma trwać tyle samo materiału i kończyć
się w tym samym punkcie utworu.

**Pliki:**
- Modyfikacja: `src/sara/audio/bass/player/flow.py` `fade_out` (l. 163-220)
- Test: `tests/test_bass_player.py` (stub z postępującą pozycją)

**Krok 1 (test):** stub, w którym `channel_get_seconds` rośnie; sprawdź, że
ustawiane głośności tworzą monotonicznie malejącą krzywę odniesioną do
przebytej pozycji `(pos - start_pos)/duration`, a `stop` następuje gdy
pokonano `duration` materiału (nie po N×sleep). Determinizm: ta sama sekwencja
pozycji → ta sama sekwencja głośności.

**Krok 2 (implementacja):** w `_runner` zamiast `factor = initial*(1 - i/steps)`
+ `sleep` licz `progress = (now_pos - start_pos)/duration`, `factor =
initial*(1-progress)`; pętla z krótkim `sleep` (np. 0.01) tylko jako takt
odpytywania, warunek końca: `progress >= 1.0` lub stream zmieniony. Zachowaj
istniejącą obsługę przerwania (zmiana `_stream`), przywracanie głośności i
`finished_callback`. BASS ma natywny `BASS_ChannelSlideAttribute` — jeśli
dostępny w `native.py`, rozważyć jego użycie w osobnym zadaniu (czystszy, w
mixtime); na teraz wersja pozycyjna wystarcza i jest backend-agnostyczna.

**Krok 3:** testy PASS. Commit `fix(fade): drive fade by stream position for repeatability`.

### Zadanie 4.2 (opcjonalne, po 4.1): Natywny slide głośności BASS

**Cel:** Najczystsza powtarzalność — `BASS_ChannelSlideAttribute(ATTRIB_VOL, 0,
ms)` wycisza w wątku BASS w mixtime, niezależnie od GIL/obciążenia.

**Pliki:**
- Modyfikacja: `src/sara/audio/bass/native.py` (prototyp), `_manager/streams.py`
  (wrapper), `flow.py` (użycie z fallbackiem do 4.1 gdy brak funkcji)
- Test: `tests/test_bass_player.py`

Realizować tylko jeśli 4.1 nie da wystarczającej powtarzalności w realnym
teście odsłuchowym. YAGNI — nie wdrażać „na zapas".

---

## Faza 5 — weryfikacja i dokumentacja

### Zadanie 5.1: Test integracyjny scenariusza miksu end-to-end (na stubach)

**Cel:** Jeden test składający emisję: utwór z segue+fade, native trigger,
sprawdza że miks następuje raz, w `mix_at`, z fade o właściwej długości,
niezależnie od kolejności wywołań callbacków.

**Pliki:** `tests/test_mix_end_to_end.py` (nowy).

### Zadanie 5.2: Pełny pytest + aktualizacja dokumentacji

**Krok 1:** `python3 -m pytest -q` → wszystko zielone.
**Krok 2:** Zaktualizuj `docs/development/track_timing.md` i
`docs/development/audio_preloading.md`: opis JEDNEJ ścieżki wyzwalania, roli
guardów (siatka bezpieczeństwa), pozycyjnego fade, jednego mechanizmu pętli.
Dodać sekcję „Determinizm: dlaczego mixtime != get_position i jak to rozdzielamy".
**Krok 3:** Commit `docs(playback): document deterministic loop/mix model`.

---

## Pliki, które najpewniej się zmienią
- `src/sara/audio/bass/player_monitor.py` (1.1)
- `src/sara/audio/bass/player/base.py` (1.2)
- `src/sara/ui/mix_runtime/now.py` (2.1)
- `src/sara/ui/mix_runtime/progress.py` (2.2)
- `src/sara/audio/bass/player/mix_trigger.py` (2.3)
- `src/sara/core/mix_planner.py` (2.2, 3.2) — nowe stałe/funkcje
- `src/sara/ui/playback/preview.py` (3.1, 3.2)
- `src/sara/audio/bass/player/flow.py` (4.1)
- `src/sara/audio/bass/native.py`, `_manager/streams.py` (4.2 opcjonalnie)
- testy: nowe + rozszerzenia istniejących
- docs/development/*.md (5.2)

## Walidacja
- Po każdym zadaniu: `python3 -m pytest <plik_testu> -v`.
- Po fazie: `python3 -m pytest -q` (baseline dziś: 56 passed, 2 skipped na
  podzbiorze; uruchomić cały zestaw).
- Test odsłuchowy na Windows (Michał): ten sam utwór, ten sam punkt — 5×
  odtworzenie pętli i 5× miks; oczekiwane identyczne wrażenie słuchowe.

## Ryzyka i otwarte pytania
- (R1) Wyłączenie guardu przy native (1.1): jeśli na jakimś sprzęcie native loop
  BASS bywa zawodny, fallback marker-sync zostaje — ale trzeba zweryfikować
  odsłuchowo, że native faktycznie zawija bezdźwięcznie. Jeśli nie — guard
  zostaje, a problemem jest konfiguracja loop points (Faza 1.2).
- (R2) Usunięcie native_wait w PFL (3.1): zakłada, że mixtime sync w PFL jest
  równie wiarygodny jak w emisji. Jest to ten sam kod managera — powinno być OK.
- (R3) Fade pozycyjny (4.1) przy bardzo krótkich fade'ach (<0.2 s) i dużym
  buforze: odpytywanie co 0.01 s daje ~kilka kroków; jeśli za mało płynne →
  Faza 4.2 (natywny slide).
- (P1) Czy chcesz, żebym usunął też legacy/płaskie duplikaty modułów (np.
  `ui/playback_controller.py` vs `ui/playback/controller.py`) czy zostawiamy?
  To osobny temat porządkowy, NIE w tym planie (izolacja zmiennej).
- (P2) Wartość bufora BASS (250 ms) zostawiamy? Mniejszy bufor zmniejsza rozjazd
  osi czasu, ale zwiększa ryzyko przerw. Mogę dodać zadanie strojenia, ale to
  zmienia działający mechanizm — domyślnie NIE ruszam.

## Kolejność wykonania (rekomendacja)
0.1 → 1.1 → 1.2 → 2.1 → 2.2 → 2.3 → 3.1 → 3.2 → 4.1 → (4.2 jeśli trzeba) → 5.1 → 5.2

Każde zadanie zamykane osobnym commitem (konwencja repo: `fix(...)`,
`refactor(...)`, `test(...)`, `docs(...)`). Komunikaty po angielsku (klucze),
treść dokumentacji po polsku z diakrytykami.
