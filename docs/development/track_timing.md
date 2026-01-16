# Czas utworu: długość pliku vs. czas antenowy

W wielu miejscach UI potrzebuje odpowiedzi na pytanie: **ile czasu utwór realnie „zajmuje antenę”**. To nie zawsze jest to samo, co długość pliku audio, bo start może być przesunięty (cue-in), a przejście do kolejnego utworu może zaczynać się wcześniej (segue/overlap lub domyślny fade).

## Definicje

- `duration_seconds` – długość pliku audio (z metadanych / backendu).
- `cue_in_seconds` – punkt startu odtwarzania (sekundy od początku pliku).
- `effective_duration` – długość po uwzględnieniu cue-in: `duration_seconds - cue_in_seconds`.
- **czas antenowy** (on-air) – czas od cue-in do punktu miksu, czyli momentu, w którym powinien zostać uruchomiony kolejny utwór.

## Jak liczymy czas antenowy

Reguły są takie same jak w planowaniu miksu:

1. Jeśli jest `segue_seconds`, to on wyznacza punkt miksu (wartość jest relatywna do cue-in).
2. W przeciwnym razie, jeśli jest `overlap_seconds`, miks startuje przy końcówce: `effective_duration - overlap_seconds`.
3. W przeciwnym razie, jeśli globalny fade (`playback_fade_seconds`) jest > 0, miks startuje: `effective_duration - playback_fade_seconds`.
4. Jeśli nie ma żadnego miksu (np. fade = 0), czas antenowy = `effective_duration`.

Wyjątki:

- `break_after` i aktywny loop traktujemy jako brak miksu → czas antenowy = `effective_duration`.

## Implementacja w kodzie

- Kanoniczna logika: `src/sara/core/mix_planner.py` (`resolve_mix_timing`, `compute_air_duration_seconds`).
- Prezentacja w playlistach (kolumny Duration/Progress): `src/sara/ui/panels/playlist/panel.py`.
- Komenda „pozostały czas utworu” i wyliczanie remaining: `src/sara/ui/controllers/playback/loop.py`.
- Alert „koniec utworu” (w praktyce: koniec antenowy / punkt przejścia): `src/sara/ui/controllers/playback/alerts.py`.

## Testy

- Testy logiki czasu antenowego są w `tests/test_mix_triggers.py` i powinny być rozszerzane razem ze zmianami w `mix_planner`.
