# Powtarzalność pętli i miksów (model deterministyczny)

Ten dokument opisuje, dlaczego pętle i miksy w SARA są powtarzalne wg zadanych
punktów (loop start/end, segue/overlap/fade, cue-in) oraz jak rozłożone są
mechanizmy, żeby ten sam materiał z tymi samymi punktami zawsze dawał identyczny
efekt słyszalny — niezależnie od obciążenia CPU i kolejności wątków.

## Dwie osie czasu: mixtime vs odtwarzanie

To jest sedno całego modelu. BASS ma dwie różne pozycje w czasie:

- **mixtime** — punkt, w którym BASS *miksuje* próbki do bufora wyjściowego.
  Wyprzedza słyszalny dźwięk o długość bufora (`SARA_BASS_BUFFER_MS`, domyślnie
  250 ms). Natywne synce ustawiane z flagą `SYNC_MIXTIME` odpalają właśnie tutaj.
- **pozycja odtwarzania** — to, co realnie słychać teraz. Zwraca ją
  `BASS_ChannelGetPosition` / `get_position_seconds()`. Jest opóźniona o bufor.

Błąd, który powodował „rozjazdy": porównywanie momentu natywnego synca (mixtime)
z `get_position` (osią odtwarzania). Różnica rzędu bufora (≈250 ms) plus jitter
odpytywania sprawiała, że ten sam punkt raz wyglądał na „za wczesny" (i kod
schodził na mniej dokładny fallback), a raz nie. Stąd niedeterminizm.

**Zasada:** natywny mixtime sync jest autorytetem. Nie weryfikujemy go pozycją
odtwarzania. `get_position` służy wyłącznie ścieżce progresowej (fallback), gdy
natywnego triggera nie ma.

## Miks emisji: jedna autorytatywna ścieżka + siatka bezpieczeństwa

Punkt miksu (`mix_at`) liczy raz `mix_planner.resolve_mix_timing` (segue >
overlap > globalny fade). Wyzwolenie:

1. **Native (główna ścieżka).** Backend uzbraja `SYNC_POS` w mixtime na
   `mix_at` (w bajtach, z odjęciem `start_offset` raz — patrz
   `audio/bass/player/mix_trigger.py`). Callback woła `auto_mix_now(..., source="native")`.
   W `mix_runtime/now.py` natywne wywołanie ufa sobie w szerokim oknie
   `MIX_NATIVE_TRUST_WINDOW` (0.75 s, wyraźnie powyżej bufora+jittera). Tylko
   rażąco wczesny callback (błędny/zduplikowany sync) schodzi na fallback.
2. **Progres (siatka bezpieczeństwa).** `mix_runtime/progress.py` pod natywnym
   triggerem NIE wyzwala miksu przed `mix_at` — czeka. Po `mix_at` (gdyby native
   zawiódł) wyzwala awaryjnie. Okno guardu liczy jedna czysta funkcja
   `mix_planner.compute_native_guard` (jedno źródło prawdy zamiast rozsianych
   wyliczeń). Dla utworów z malutkim zapasem po miksie wyznacza miękkie
   wcześniejsze zwolnienie (`release_offset`), by zdążyć z fade'em.

Fire-once gwarantują flagi `plan.triggered` i `auto_mix_state[key]`. Native i
progres nie mogą wyzwolić miksu dwa razy (test:
`tests/test_mix_end_to_end.py`).

## PFL (podsłuch miksu): też jedna ścieżka

`ui/playback/preview.py::start_mix_preview` uzbraja native trigger na playerze A
i odpala przez `_fire_mix("native")`. Timer fallback działa tylko gdy backend
nie wspiera natywnego triggera albo native nie odpalił w oknie `delay + guard`
(strzeże tego `fired_event`). Usunięto wcześniejsze odraczanie
„native trigger early -> position wait", bo porównywało mixtime z pozycją
odtwarzania (ten sam błąd osi czasu). Okno podglądu liczy `preview_window`.

## Pętla: jeden mechanizm zawijania

- **Native (główny).** Gdy BASS wspiera loop points, ustawiamy je
  (`POS_LOOP`/`POS_END`) i flagę `SAMPLE_LOOP`. BASS zawija próbka-w-próbkę w
  mixtime — bezszwowo. Koniec pętli jest przycinany do długości materiału
  (`_apply_loop_settings`), bo punkt poza plikiem psuje natywną pętlę.
- **Fallback (marker-sync).** Gdy native niedostępny, używamy `SYNC_POS` na
  końcu pętli + pythonowego strażnika w `player_monitor.py`, który dорzuca skok
  gdy pozycja przekroczy koniec.

**Kluczowe:** pythonowy strażnik działa WYŁĄCZNIE w trybie fallback. Decyduje o
tym czysta funkcja `player_monitor.loop_guard_reason`, która przy
`native_active=True` zawsze zwraca `None`. Wcześniej strażnik skakał także przy
aktywnej pętli natywnej — dublował zawijanie BASS i groził podwójnym skokiem /
kliknięciem / mikro-dryfem.

## Fade: sterowany pozycją, nie zegarem

`audio/bass/player/flow.py::fade_out` wyznacza głośność z PRZEBYTEJ pozycji
strumienia: `progress = (pos - start_pos) / duration`. Pętla wątku tylko
odpytuje pozycję co ~10 ms (takt), ale długość i kształt krzywej zależą od
materiału, nie od liczby wykonanych `sleep`. Dzięki temu pod obciążeniem CPU
fade trwa tyle samo materiału i kończy się w tym samym punkcie utworu
(a więc `stop` + `finished_callback` wypadają powtarzalnie). Gdy pozycja jest
niedostępna, fade degraduje bezpiecznie do natychmiastowego wyciszenia.

## Stałe i funkcje (mix_planner.py)

- `MIX_NATIVE_TRUST_WINDOW` (0.75 s) — okno zaufania dla natywnego callbacku.
- `MIX_NATIVE_EARLY_GUARD` / `MIX_NATIVE_LATE_GUARD` / `MIX_EXPLICIT_PROGRESS_GUARD`
  — progi ścieżki progresowej.
- `MIX_NATIVE_SAFETY_NET` — bazowy próg siatki bezpieczeństwa.
- `compute_native_guard(...)` — całe okno guardu progresowego w jednym miejscu.
- `preview_window(mix_at, pre_seconds)` — wspólne okno podglądu PFL.
- `resolve_mix_timing` / `compute_air_duration_seconds` — punkt miksu i czas antenowy.

## Mapa kodu

- Punkt miksu / czas antenowy: `src/sara/core/mix_planner.py`.
- Natywny wyzwalacz miksu (mixtime, fire-once): `src/sara/audio/bass/player/mix_trigger.py`.
- Pętla (native + fallback, clamp do długości): `src/sara/audio/bass/player/base.py`.
- Strażnik pętli (tylko fallback): `src/sara/audio/bass/player_monitor.py` (`loop_guard_reason`).
- Adaptacyjny takt monitora: `src/sara/audio/bass/player_monitor.py` (`python_guard_active`).
- Fade pozycyjny: `src/sara/audio/bass/player/flow.py` (`fade_out`).
- Automix natychmiastowy (native): `src/sara/ui/mix_runtime/now.py`.
- Automix progresowy (siatka): `src/sara/ui/mix_runtime/progress.py`.
- PFL podsłuch miksu: `src/sara/ui/playback/preview.py`.

## Testy

- `tests/test_mix_trigger_determinism.py` — fire-once wyzwalacza miksu.
- `tests/test_bass_player.py` — pętla (native/fallback/clamp), guard, fade pozycyjny, domena bajtów.
- `tests/test_mix_triggers.py` — `compute_native_guard`, `preview_window`,
  zaufanie do native w oknie bufora, fallback przy rażąco wczesnym callbacku.
- `tests/test_pfl_mix_preview_preloading.py` — jedna ścieżka PFL.
- `tests/test_mix_end_to_end.py` — integracja: miks raz w punkcie, brak podwójnego wyzwolenia.

## Adaptacyjny takt monitora (jitter dyspozycji po dłuższej sesji)

Objaw (zaobserwowany 19.06.2026 na odsłuchu PFL Alt+V): na świeżym procesie
punkt miksu jest powtarzalny co do milisekund, a po ~2 h pracy zaczyna „pływać"
(raz szybciej, raz wolniej). W logach: przy stałym `delay=1.400` realny czas od
startu A do odpalenia (`elapsed`) jest na starcie ~0.979–0.985 s (rozrzut ~6 ms),
a po 2 h ~0.917–0.978 s (rozrzut ~60 ms). Wszystkie odpalenia idą jedną ścieżką
(`source=native`, `via=pos`) — to NIE wyścig ścieżek, lecz rosnący jitter
dyspozycji pythonowego callbacku miksu pod GIL.

Przyczyna: monitor każdego `BassPlayer` kręcił się w `time.sleep(0.001)`
(busy-loop 1 ms). Ten ciasny takt jest potrzebny WYŁĄCZNIE pythonowemu
strażnikowi pętli w trybie marker-sync (gdy natywna pętla BASS niedostępna).
W odsłuchu PFL każde przezbrojenie tworzy dwa nowe playery grające bez pętli —
ich monitory 1 ms tylko niepotrzebnie napierały na scheduler OS. Przy
dziesiątkach przezbrojeń presja kumuluje się i rośnie jitter.

Poprawka: czysta funkcja `python_guard_active(player)` decyduje, czy ciasny takt
jest realnie potrzebny (pętla aktywna ORAZ marker-sync ORAZ strażnik włączony).
Gdy nie — monitor pracuje w takcie `_MONITOR_IDLE_INTERVAL` (20 ms). Postęp i tak
jest dławiony do 50 ms, a koniec strumienia wykrywany z zapasem, więc luźniejszy
takt niczego nie psuje, a usuwa źródło jittera. Decyzja jest podejmowana co
iterację, więc włączenie pętli w locie natychmiast wraca do taktu 1 ms.

Diagnostyka na przyszłość: `_fire_mix` w `preview.py` loguje teraz wiersz
`PFL mix preview: timing ... b_latency=... threads=...`. Rosnący `b_latency`
(latencja faktycznego startu playera B) lub `threads` (liczba żywych wątków
procesu) przy stałym `delay` to sygnatura jitteru z kumulacji zasobów — pierwszy
sygnał, gdzie szukać, gdyby punkt miksu znów zaczął „pływać".

## Strojenie bufora

`SARA_BASS_BUFFER_MS` (domyślnie 250) wpływa na rozjazd osi mixtime vs
odtwarzanie. Mniejszy bufor = mniejsza różnica, ale większe ryzyko dropów. Model
deterministyczny jest odporny na typowy bufor dzięki oknu zaufania — nie ma
potrzeby zmniejszać bufora, by uzyskać powtarzalność.
