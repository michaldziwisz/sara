# Organizacja kodu i próg refaktoru (SARA)

Ten dokument ma pomóc utrzymać porządek w repozytorium przy długim i intensywnym rozwoju — bez „refaktoru dla refaktoru”.

## Warstwy i zależności (najważniejsza zasada)

Trzymaj zależności w jednym kierunku:

- `sara/core`: logika biznesowa, modele, parsowanie, planowanie (bez `wx`, bez `sara.ui`).
- `sara/audio`: backendy audio, miksowanie, typy audio (bez `wx`, bez `sara.ui`).
- `sara/ui`: wxPython (okna, panele, dialogi) + kontrolery/serwisy UI, które integrują `core` i `audio`.

Reguła: jeśli logika da się przetestować bez UI, **niech żyje w `core` albo w testowalnych helperach `ui` bez `wx`**.

## Kanoniczne miejsca na nowy kod (żeby nie wrócić do „mega-plików”)

Nowy kod dodawaj do „docelowych” pakietów, a nie do wrapperów kompatybilności.

- **Kontrolery UI / glue**: `src/sara/ui/controllers/<obszar>/...`
  - przykłady obszarów: `playback`, `playlists`, `mix`, `news`, `menu`, `frame`, `tools`, `jingles`.
- **Dialogi**: `src/sara/ui/dialogs/<obszar>/...`
- **Panele**: `src/sara/ui/panels/<obszar>/...`
- **Serwisy UI (bez widgetów)**: `src/sara/ui/services/...` (np. undo/clipboard/announcements/NVDA)
- **Playback**: `src/sara/ui/playback/...` (kontekst, preview, device selection, start helpers)
- **Skróty**: `src/sara/ui/shortcuts/...`
- **Helpery plików**: `src/sara/ui/files/...`
- **Layout/stan UI bez wx**: `src/sara/ui/layout/...`

Wrappery w `src/sara/ui/*.py` traktuj jako **warstwę kompatybilności** (stare importy), nie jako miejsce na rozwój.

## Próg refaktoru (kiedy rozcinać, a kiedy zostawić)

To nie są „twarde limity”, tylko progi alarmowe — jeśli je przekraczasz, rozważ podział.

### 1) Rozmiar pliku (heurystyka)

- Moduły „czystej logiki” (`core`, helpery bez `wx`): ~`> 250–350` linii → rozważ podział.
- Kontrolery UI (`ui/controllers`, `ui/playback`, `ui/services`): ~`> 350–500` linii → rozważ podział.
- Widoki / dialogi / panele (`wx`): ~`> 500–700` linii → rozważ podział na moduły „UI” + „logika”.

Jeśli plik jest większy, ale ma jedną spójną odpowiedzialność i rzadko się zmienia — zostaw.

### 2) Zbyt wiele odpowiedzialności (ważniejsze niż linie)

Rozcinaj, gdy jeden moduł zaczyna mieszać 2+ z poniższych:

- UI (wx widgets, binding eventów)
- logika domenowa (reguły miksu, wybór następnego utworu, walidacje)
- I/O (pliki, konfiguracje, import/export)
- integracje backendów (audio, NVDA)
- wątki/timery/async (konkurencja)

Zasada praktyczna: **UI moduł powinien głównie „zbierać dane + wywoływać kontroler/serwis”**.

### 3) Cykle importów i przecieki warstw

Refaktor jest „obowiązkowy”, jeśli:

- `sara/core` zaczyna importować `wx` albo `sara.ui`
- moduły w `ui/controllers` muszą importować `MainFrame` (zamiast przyjmować `frame`/interfejs)
- pojawiają się cykliczne importy między obszarami (np. `playlists` ↔ `playback`)

### 4) Konflikty i częstotliwość zmian (z perspektywy intensywnego rozwoju)

Jeśli jeden plik jest dotykany w prawie każdym PR i regularnie generuje konflikty, podział ma sens nawet przy mniejszej liczbie linii — to realnie przyspiesza pracę zespołu.

## Zasady wrapperów kompatybilności (żeby było bezpiecznie)

Kiedy przenosisz klasę/funkcję/moduł:

1. Przenieś implementację do „kanonicznego” miejsca (np. `ui/controllers/...`).
2. Zostaw wrapper w starej ścieżce importu, który **re-exportuje** API (`__all__` + importy).
3. Nowy kod w repo powinien importować **z kanonicznego miejsca**, nie z wrappera.
4. Uruchom testy: `PYTHONPATH=src venv_codex/bin/python -m pytest -q`.
5. Zrób mały checkpoint commit.

## Minimalna polityka „czy dopisywać nowy plik?”

Dodaj nowy plik/podpakiet, jeśli:

- wprowadzasz nową funkcję/feature, która ma własną odpowiedzialność,
- przewidujesz, że będzie rosła (więcej opcji, stanów, wariantów),
- albo chcesz ograniczyć konflikty w często zmienianych miejscach.

Nie dodawaj nowego pliku, jeśli:

- to 1–2 krótkie funkcje używane tylko lokalnie,
- a rozdział utrudni nawigację (skakanie po plikach bez zysku).

