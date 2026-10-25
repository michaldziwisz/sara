# Weryfikacja automatycznego wyrównywania głośności

Zadanie: `t_83e8bef8`. Baza: `4f2184c`. Kod, testy i tłumaczenie: `e59ff7658730560be50d5fb1ddf0eaa81a3bebc4`.

## Wyniki

| Sprawdzenie | Wynik |
| --- | --- |
| Pierwsze testy przed implementacją | 11 failed, 13 errors: brak usługi, ustawienia, true peak i wspólnego wyniku |
| Pełny pytest pod Xvfb | 428 passed, 8 skipped |
| Wszystkie testy remote z włączonym GUI | 187 passed |
| Kontrola dodatnia mutacji | 22 passed |
| Mutacje | 22/22 zabite asercjami, w tym 5 nowych |
| Nowe moduły i testy, analizator, skrypt mutacyjny: Ruff | All checks passed |
| `git diff --check` | Bez błędów |
| Gettext PO i MO | Jeden nowy napis, wszystkie wcześniejsze tłumaczenia identyczne |
| Trzy nieśledzone pliki użytkownika | SHA-256 zgodne z tabelą w `remote_control_tests.md` |

Osiem pominięć to trzy moduły Windows bez pywinauto, trzy moduły GUI opt-in i dwa testy wymagające `logs/saramix.m3u`. Nowy moduł GUI loudness nie jest opt-in i wykonał się w pełnym przebiegu. Testy remote uruchomiono także osobno z `WX_RUN_GUI_TESTS=1`.

Dodatkowa próba remote wraz z testami okna plików przekroczyła limit 120 s. Osobne uruchomienie okna plików potwierdziło zatrzymanie istniejącego `test_file_dialog_remembers_last_directory` w `_confirm_selection`, linia 232, po pozytywnym pierwszym teście. Faulthandler zapisał stos po 20 s; proces przerwał limit 50 s. Ten sam test był już wskazany w archiwalnym raporcie sterowania TCP. Kod i testy okna plików są niezmienione. Nie zaliczamy tego dodatkowego przebiegu jako zielonego.

## Co sprawdzają nowe testy

1. Trzy różne pliki, jeden identyfikator wątku pomiarowego różny od GUI, rzeczywisty zapis APE i odczyt wyniku.
2. Znacznik po ponownym wczytaniu M3U, cudzy ReplayGain, duplikaty ścieżki, priorytet wyniku SARY nad wcześniejszym ID3.
3. EBU i ATSC, ograniczenie TP, zakres odtwarzacza, ujemna wartość -8,87 bez błędu zaokrąglenia, odrzucanie nieskończoności i NaN.
4. Ochrona gainu podczas grania i pauzy, preloadu, PFL oraz strumienia bez kontekstu. Prawdziwy kontroler odtwarzania z atrapą playera zachowuje stary gain, a przy następnym starcie pobiera nowy.
5. Preload jeszcze pracujący w executorze oraz następny preload wysłany po ukończeniu wcześniejszej bariery. Drugi przypadek ujawnił i usunął wyścig w pierwszej wersji ochrony zapisu.
6. Brak analizatora, pomiar zakończony błędem, błąd zapisu i ponowienie zapisu po wczytaniu bez kolejnego pomiaru, zatrzymanie kolejki i odrzucenie późnego wyniku po zamknięciu.
7. Prawdziwe okna wx: start programu, pliki, M3U, schowek, timer, domyślne zaznaczenie, polska etykieta i nazwa dostępności pola, zapis Opcji, przycisk normalizacji EBU i ATSC.
8. Flagi procesu Windows, limit 120 s wspólny dla analizatora, kopii tymczasowej i transkodowania; bez ponawiania po timeout.

Pięć nowych mutantów usuwa ograniczenie TP, zmienia gain grającego playera, ignoruje znacznik, przenosi pomiar do GUI i zapisuje plik mimo aktywnego kontekstu. Pozostałe 17 sprawdza wcześniejsze zachowanie TCP, Hold i Mix. Mutacje istnieją wyłącznie w pamięci procesu; skrypt wymaga błędu asercji, nie awarii importu.

## Prawdziwy analizator w WSL

Lokalny `bs1770gain 0.8.8` z FFmpeg 6 po włączeniu true peak potrafi zwrócić kod 0 i XML z pozorną wartością -70 LUFS mimo komunikatu `Error: converting frame: Input changed (ff_resampler.c...)`. Taki wynik jest teraz odrzucany. Poprawny XML po nieudanym retry z kodem niezerowym też nie jest uznawany za sukces.

Dodatni test integracyjny generuje WAVEX 192 kHz z jawnym układem kanałów, omijając wadliwy upsampler tej lokalnej kombinacji bibliotek. Naprawdę uruchamia analizator, sprawdza LUFS i TP, zapisuje i odczytuje znacznik APE oraz porównuje próbki audio przed i po zapisie. Istniejący test `beep.wav` wymaga poprawnego wyniku albo jawnego odrzucenia dokładnie rozpoznanego błędu upsamplera. Nie pominięto go ani nie podstawiono mu wymyślonego wyniku. Test integracyjny jest pomijany wyłącznie przy braku analizatora.

To nie potwierdza działania Windows EXE ani poprawności lokalnego analizatora dla każdego formatu.

## Granice i decyzje implementacyjne

Usługa obserwuje modele playlist co 500 ms, dzięki czemu obejmuje także wczytywanie startowe i istniejące ścieżki schowka. Tylko playlisty `MUSIC` uruchamiają pomiary. Wspólna funkcja w `core/loudness.py` oblicza wzmocnienie i znacznik dla automatu oraz przycisku.

Model jest aktualizowany przez `wx.CallAfter`. Usługa nie woła `player.set_gain_db`. Oprócz kontekstów i gotowych preloadów obserwuje niezakończone zadania executora przez przezroczysty adapter. Nie zmienia implementacji odtwarzania ani protokołu TCP.

Końcowy zapis APE pozostaje synchroniczny w turze GUI, po sprawdzeniu zajętości pliku. Zapobiega to wciśnięciu startu utworu między sprawdzenie a zapis. Odroczona kolejka zapisuje najwyżej jeden plik na wywołanie. Pomiar i transkodowanie nie wykonują się w GUI. Nie zmierzono czasu końcowego zapisu na wolnym lub niedostępnym udziale sieciowym; test innego wątku subprocessu nie dowodzi nieblokującego I/O tagów. Ten punkt wymaga uwzględnienia przy odbiorze.

Niesprawdzone: Windows, prawdziwy BASS, zapis do otwartego pliku na Windows, NVDA, odsłuch na antenie i latencja sieciowego zapisu tagów. Zapis do rozpoznanych otwartych plików jest zawsze odkładany. Testy z atrapami nie są dowodem jakości dźwięku ani gotowości do wdrożenia na stanowisku emisji.

Porównanie:

```sh
git diff --stat 4f2184c..HEAD -- src/sara/audio src/sara/ui/playback src/sara/ui/mix_runtime
```

jest puste. `src/sara/remote` także pozostał bez zmian. Nie było pushu, buildu EXE, wdrożenia ani dostępu do `/mnt/d`. Nieśledzonych plików Michała nie dodawano do commitów.

## Odtworzenie

```sh
source .venv/bin/activate
export LD_LIBRARY_PATH="$PWD/.venv/system/root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export TMPDIR="$PWD/.venv/tmp"
export PATH="$PWD/.venv/system/root/usr/bin:$PATH"
nice xvfb-run -a python3 -m pytest -q tests -rs -p no:cacheprovider
WX_RUN_GUI_TESTS=1 nice xvfb-run -a python3 -m pytest -q tests/test_remote_*.py -p no:cacheprovider
nice xvfb-run -a python3 scripts/check_remote_mutations.py
```

Logi w `.venv/tmp/`: `auto-loudness-red.log`, `auto-loudness-verified.log`, `auto-loudness-mutations-verified.log`, `auto-loudness-remote-only.log`, `auto-loudness-file-gui.log`. Ruff całej listy zmienionych plików ujawnił ponadto wcześniejszy, niezmieniony import `Optional` w `core/app_state.py`; nie usuwano go porządkowo.
