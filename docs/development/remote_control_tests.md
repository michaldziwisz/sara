# Weryfikacja lokalnego sterowania TCP

Zadanie: `t_9082ea5d`. Punkt bazowy: `00927d5`. Implementacja: `e6356184deef867b5294698582fd44414fc87a78`.

## Wynik

Protokół, integracja z główną ramką wx, ustawienia oraz wymagane testy mutacyjne są sprawdzone lokalnie. Funkcja nie była budowana do EXE, wypychana ani wdrażana. Nie wykonano odsłuchu BASS na Windows, pomiaru NVDA ani testu z fizycznym X-TOUCH. Te czynności należą do odbioru na stanowisku emisji.

| Przebieg | Wynik |
| --- | --- |
| Bazowy pełny pytest, przed zmianami, zapisany w karcie | 223 passed, 6 skipped, 1 failed |
| Końcowy pełny `python3 -m pytest -q` pod Xvfb | 285 passed, 7 skipped, 1 failed |
| Końcowy zestaw z wyłączeniem wyłącznie znanego testu bs1770gain | 285 passed, 7 skipped, 1 deselected |
| Nowe testy z jawnym włączeniem GUI wx | 77 passed |
| Mutant nasłuchu na `0.0.0.0` | Zabity, test kończy się kodem 1 i AssertionError |
| Mutant wykonujący polecenie w wątku klienta | Zabity, test kończy się kodem 1 i AssertionError |
| Import modułów remote bez załadowania wx | Poprawny, Helo korzysta z wersji 0.0.37 |
| Kompilacja modułów Python i `git diff --check` | Poprawne |

Jedyna porażka końcowego pełnego zestawu to `tests/test_loudness.py::test_analyze_loudness_returns_value`: `WSL UtilAcceptVsock:281: accept4 failed 110`, przy uruchamianiu bs1770gain. Występowała przed zmianą i została dopuszczona jako znany błąd środowiska w decyzji rodzica. Jest niestabilna: pośredni pełny przebieg przeszedł, lecz końcowy ponownie wykazał ten sam błąd. Nie oznaczamy końcowego pełnego zestawu jako zielonego i nie zmienialiśmy testu ani analizatora głośności, by go ukryć.

Dodatkowy eksperyment z `WX_RUN_GUI_TESTS=1` dla całego repozytorium został przerwany limitem 180 sekund po 40 testach, przed rozpoczęciem testów remote. Według kolejności kolekcji następny był istniejący `test_file_dialog_remembers_last_directory`. Samo to nie dowodzi przyczyny zawieszenia. Wszystkie nowe testy GUI uruchomione oddzielnie przeszły. Po przerwaniu nie pozostały procesy pytest ani Xvfb. Nie modyfikowano istniejących testów okna plików.

## Odtworzenie w lokalnym środowisku

Środowisko `.venv` korzysta z Pythona 3.12 i systemowego wxPython. PortAudio rozpakowano lokalnie w repozytorium; nie instalowano pakietów systemowych.

```sh
cd /home/ubuntu/emisja
source .venv/bin/activate
export LD_LIBRARY_PATH="$PWD/.venv/system/root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export TMPDIR="$PWD/.venv/tmp"
xvfb-run -a python3 -m pytest -q
xvfb-run -a python3 -m pytest -q -k 'not test_analyze_loudness_returns_value'
WX_RUN_GUI_TESTS=1 xvfb-run -a python3 -m pytest -q tests/test_remote_commands.py tests/test_remote_server.py tests/test_remote_settings.py tests/test_remote_gui.py
python3 scripts/check_remote_mutations.py
```

Mutanty powstają wyłącznie w pamięci oddzielnych procesów. Skrypt nie podmienia produkcyjnych plików. Warunkiem zaliczenia jest błąd asercji konkretnego testu, nie błąd importu lub składni.

Surowe wyniki lokalne:

* `.venv/remote-full-pytest.log`;
* `.venv/remote-regression-pytest.log`;
* `.venv/remote-targeted-pytest.log`;
* `.venv/remote-mutations-pytest.log`.

## Pokrycie nowej funkcji

* Wszystkie polecenia, małe i wielkie litery, przecinki, LF/CRLF, nieznane polecenie i błędne parametry.
* Prawdziwe gniazda TCP, port 0, fragmentacja transmisji, kilku klientów i niezależne migawki Stat.
* Ścisły bind do 127.0.0.1, odrzucenie innych adresów źródłowych i konflikt zajętego portu.
* Przekazanie wykonania do rzeczywistego `wx.CallAfter` i kontrola identyfikatora głównego wątku.
* Timeout bez późniejszego wykonania polecenia oczekującego w kolejce; zamknięcie ramki unieważniające oczekujące polecenia i zamykające gniazda.
* Restart tego samego portu po zamknięciu przyjętego klienta; limit linii i błędne UTF-8.
* Faktyczny `MainFrame`, jego uruchomienie serwera i zamknięcie; backend audio zastąpiony atrapą.
* Play i Skip przez rzeczywisty kontroler nawigacji w trybie ręcznym, automiksie i naprzemiennym; brak playlisty.
* Stop, Instant Stop i Pause przez rzeczywisty kontroler skrótów, z istniejącym obliczeniem czasu wyciszenia. Powtórne Pause nie wznawia ani nie ogłasza ponownie pauzy.
* Zmiana podświetlenia i znacznika do emisji na rzeczywistym PlaylistPanel. Fokus innego okna wx pozostaje bez zmian.
* Format TrackInfo/TrackInfoEx, znaki specjalne, statusy, czasy względem cue i preferowanie klucza NowPlaying.
* Utrwalanie ustawień, błędne wartości konfiguracji, polskie etykiety dostępności, akceptacja Opcji i rekonfiguracja usługi.
* Zgodność wersji awaryjnej w `src/sara/__init__.py` z wersją w `pyproject.toml`; obie należy aktualizować przy wydaniu.

## Ochrona istniejących mechanizmów

Porównanie Git z `00927d5` wykazało brak zmian w:

* `src/sara/audio/`;
* `src/sara/core/playlist.py` oraz `src/sara/core/mix_planner.py`;
* `src/sara/ui/controllers/playback/` oraz `src/sara/ui/controllers/playlists/`;
* `src/sara/ui/mix_runtime/`, `src/sara/ui/playback/`, `src/sara/ui/panels/`;
* `src/sara/ui/services/now_playing.py`.

Nie dodano zależności do manifestu. Integracja z istniejącym kodem obejmuje ustawienia, uruchomienie i zamknięcie usługi w MainFrame oraz zastosowanie opcji. Backendów audio, punktów cue, pętli, miksu i PFL nie zmieniano.

Nowy katalog MO zawiera pięć nowych tłumaczeń. Porównanie katalogów gettext wykazało, że wszystkie wcześniejsze tłumaczenia są identyczne.

Trzy pliki użytkownika pozostają nieśledzone i niezmienione. Ich SHA-256 zgadzają się z wejściowymi:

| Plik | SHA-256 |
| --- | --- |
| `.hermes/plans/2026-06-19_182430-kompensacja-pozycji-b.md` | `94eb04e0d8fef6f474c6ea0aa70ee2fec890333d24d79080862b4bf66b9680df` |
| `docs/opis-sara.docx` | `d428356bd0ca48c68c89263123fa589fb4e38cf42b999b6d74940d8ad4403c1a` |
| `docs/opis-sara.md` | `a14de62d8e4ca693698823f961bf4568e1f7a1c41327ef8ce79659d64cc72343` |

## Granice kontraktu

Dokładny kontrakt dla klienta opisuje [dokumentacja użytkowa](../sterowanie-tcp.md). Stat porównuje migawki modelu, a nie rejestruje każdej przejściowej zmiany. Next wskazuje kandydata bez sprawdzania pliku lub urządzenia. Operacje dotyczą aktywnej playlisty muzycznej, tak jak istniejące skróty. Pause jest świadomie tylko wstrzymaniem, zgodnie z decyzją rodzica; nie dodano resume.
