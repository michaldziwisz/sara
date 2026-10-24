# SARA (Simple Accessible Radio Automation)

SARA is a wxPython-based automation suite for radio stations. It provides multiple playlists, independent audio outputs (WASAPI/ASIO), extensive keyboard control, and screen-reader friendly UI.

---

## 🇬🇧 English
### Status
*Work in progress* – playback, multiple players per playlist, and loop tools are functional.

### Quick start
1. Install system prerequisites (wxWidgets, audio backends such as WASAPI/ASIO where required).
2. Optionally download [BASS](https://www.un4seen.com/) and place `bass.dll` next to the project (or set `BASS_LIBRARY_PATH`).
3. Install [FFmpeg](https://ffmpeg.org/) if you plan to play MP4/M4A audio (the executable must be visible in `PATH`).
4. Create a virtualenv for Python 3.11+: `python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`).
5. Install dependencies: `pip install -r requirements-dev.txt`.
   - Optional ASIO support: `pip install pythonnet>=3.0.3` (or `pip install -e .[asio]`).
6. Run the app: `python -m sara.app`.
7. In the UI:
   - Add a playlist (`Ctrl+N`).
   - Add tracks (`Ctrl+D`).
   - Map players/devices (`Ctrl+Shift+D`).
   - Set a marker with `Enter` and toggle marker mode (`Ctrl+Shift+Enter`) so global `Space` starts from it.
   - Playlist controls: `F1` play, `F2` pause, `F3` stop, `F4` fade out, `Ctrl+Shift+L` toggle loop, `Ctrl+Shift+M` auto-mix.
   - Loop dialog (`Shift+F10 → Loop…`): fine-tune start/end, capture preview (`Ctrl+P` / `Ctrl+Shift+P`). Loop ranges are saved in APEv2 tags (`SARA_LOOP_*`).
   - Use `Ctrl+Shift+L` to toggle looping per track; `Ctrl+Alt+Shift+L` announces loop info.
   - Options (`Tools → Options…`) let you adjust fade out, PFL device, startup playlists, alternate play mode and auto removal of played tracks.
   - Startup playlists in Options can now include both music and news panels, so you can reopen newsroom scripts automatically at launch.
   - Edit menu provides standard clipboard actions, move items with `Alt+↑/↓`.
   - News playlists expose `Load service…` / `Save service…` buttons (and `Ctrl+O` / `Ctrl+S`) to import/export `.saranews` files. The same format is available in the standalone `sara-news-editor` app, which remembers the last device you picked and lets newsroom staff preview clips without launching the full SARA UI.
   - Press `Ctrl+E` to toggle between edit and read-only mode; in read-only you can use `H`/`Shift+H` to jump headings, `C`/`Shift+C` to jump audio clips, and Tab to reach the toolbar (device chooser, line length, Apply).

You can also paste straight from the system clipboard: copy audio files or folders in the Explorer, then press `Ctrl+V` in a playlist — SARA will expand folders, extract metadata, and insert tracks in place.

Configuration is stored in `config/settings.yaml`, but editing through the Options dialog is recommended. Bundled BASS binaries (Windows/Linux) are provided for convenience; commercial usage requires a license from Un4seen.

### Accessibility & NVDA
- On startup SARA installs/updates its NVDA helper (`sara.ui.nvda_sleep`) so NVDA keeps quiet unless the playlist explicitly opens the speech window.
- The repository ships an NVDA add-on (`artifacts/sara-silent-addon.nvda-addon` in releases) that keeps Play Next silent while letting arrow navigation read every track. Install it via NVDA’s “Manage Add-ons” dialog for the best experience.
- Playlist selection changes are optimized for screen readers; when audio focus switches back to a playing item, NVDA receives just one concise announcement.

### Tests
```
PYTHONPATH=src python -m pytest
```
UI/E2E on Windows (optional): `RUN_SARA_E2E=1 PYTHONPATH=src python -m pytest -m e2e tests/e2e` (uses mock audio, isolated config under `SARA_CONFIG_DIR`).

### Repository layout
```
./docs           # documentation and project notes
./src/sara       # application sources
./tests          # unit and integration tests
```

### Key features
- Multiple playlists with configurable output slots and device assignments.
- Streamed audio playback (sounddevice/pycaw/pythonnet) with ReplayGain support.
- Rich keyboard control and clipboard operations.
- Loop dialog with PFL preview and persistent loop metadata.
- Sample-accurate intro looping on BASS-based players.
- News playlists with Markdown editing, per-line read mode, and inline audio buttons.
- Music folder playlists: assign a directory, preview on the PFL device with `Space`, and press `Enter` to send tracks to the active music playlist.
- `.saranews` import/export plus a standalone News Editor (`sara-news-editor`) with persistent audio-device selection for preparing services outside the studio.
- Options dialog for fade, PFL device, startup playlists, language, alternate play, auto-remove.
- Screen-reader announcements (NVDA) and coverage in the test suite.

#### News playlists
- **Edit mode (`Ctrl+E`):** plain Markdown editor with `Ctrl+V` clipboard paste (files/folders or `[[audio:path]]` placeholders). Use the toolbar buttons to load/save `.saranews` packages or insert audio from the system clipboard.
- **Read-only mode (`Ctrl+E` again):** the text is wrapped to the configured line length; `H`/`Shift+H` jumps between headings, `C`/`Shift+C` between audio markers, `Enter`/`Space` plays the clip under the caret, and Tab moves focus to the toolbar (Load/Save, line length spinner, Apply, device selector).
- **Standalone editor (`sara-news-editor`):** shares the same panel, stores its configuration in `config/news_editor.yaml` next to the executable, remembers the last device, and lets newsroom staff edit `.saranews` files without running the full SARA UI.

### Packaging & release
- Ensure locale and vendor binaries are included (`MANIFEST.in`, `pyproject.toml`).
- Build distributables with `python -m build`; the `sara` console entry starts the GUI.
- GitHub Actions provides a **Windows Build** workflow that publishes a downloadable `.zip` (containing `dist/SARA`) on every push to `main` and on tagged releases.
- The Windows zip now ships both `SARA.exe` and `SARA-News-Editor.exe`, sharing the same runtime files, NVDA/BASS DLLs, and an `ffmpeg.exe` helper for MP4/M4A playback.
- The CI bundle includes NVDA controller DLLs and the Windows `bass.dll` so speech and optional BASS playback work out of the box.
- The workflow also copies the bs1770gain CLI (`src/sara/audio/vendor/windows/bs1770gain`) next to `SARA.exe`; do the same when preparing local PyInstaller builds so normalization keeps working.
- Scripts `scripts/auto_download.sh` and `scripts/download_latest_artifact.sh` (install via `scripts/install_hooks.sh`) keep the latest Windows artifact under `artifacts/` after each successful build.
- For frozen Windows builds, bundle NVDA controller DLLs and optional BASS binaries alongside the executable.
- Release notes live in `docs/releases/` (see `docs/releases/0.0.32.md` for the latest changes).

### Roadmap highlights
- Enhanced accessibility messages.
- Persisting extra track parameters.
- Advanced fade/crossfade scenarios and scheduling.
- Separate buffer settings for main players and PFL.
- Intro/outro mix-point editor compatible with StationPlaylist tags.
- Spoken countdown for remaining intro time and shortcut for remaining track time.
- Overlay playlist type that mixes without fading other outputs.
- Finer control over accessibility announcements.
- Investigate preloading tracks into memory to minimize disk I/O at cue time.

### License
- Application code: BSD 3-Clause (see `LICENSE`).
- Bundled BASS libraries retain Un4seen licensing (see `src/sara/audio/vendor/bass.txt`).
- NVDA Controller binaries are distributed under the [NV Access license](https://www.nvaccess.org/about-nvda/license-and-credits/); use subject to their terms.

---

## 🇵🇱 Polski
### Status
Wersja rozwojowa – odtwarzanie, wielokrotne sloty odtwarzaczy i narzędzia pętli są gotowe.

### Szybki start
1. Zainstaluj zależności systemowe (wxWidgets, backendy audio typu WASAPI/ASIO).
2. (Opcjonalnie) pobierz [BASS](https://www.un4seen.com/) i umieść `bass.dll` w katalogu projektu (lub ustaw `BASS_LIBRARY_PATH`).
3. Zainstaluj [FFmpeg](https://ffmpeg.org/), jeśli chcesz odtwarzać pliki MP4/M4A (plik `ffmpeg.exe` musi być w `PATH`).
4. Utwórz wirtualne środowisko Python 3.11+: `python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`).
5. Zainstaluj zależności projektu: `pip install -r requirements-dev.txt`.
   - Opcjonalna obsługa ASIO: `pip install pythonnet>=3.0.3` (lub `pip install -e .[asio]`).
6. Uruchom aplikację: `python -m sara.app`.
7. W interfejsie:
   - Dodaj playlistę (`Ctrl+N`).
   - Dodaj utwory (`Ctrl+D`).
   - Przypisz odtwarzacze/urządzenia (`Ctrl+Shift+D`).
   - Ustaw znacznik klawiszem `Enter`, a tryb od znacznika (`Ctrl+Shift+Enter`) sprawi, że Spacja startuje od niego.
   - Sterowanie playlistą: `F1` – start, `F2` – pauza, `F3` – stop, `F4` – fade out, `Ctrl+Shift+L` – pętla, `Ctrl+Shift+M` – auto mix.
   - Dialog pętli (`Shift+F10 → Zapętl…`): precyzyjne start/koniec, odsłuch PFL (`Ctrl+P` / `Ctrl+Shift+P`). Pętle zapisują się w tagach APEv2.
   - Przełączanie zapętlenia utworu (`Ctrl+Shift+L`) i informacja o pętli (`Ctrl+Alt+Shift+L`).
   - `Narzędzia → Opcje…` udostępniają sterowanie fade, urządzeniem PFL, playlistami startowymi, językiem, trybem naprzemiennym i auto-usuwaniem.
   - W sekcji Startup playlists możesz dodać zarówno playlisty muzyczne, jak i newsowe, żeby po starcie Sary od razu otwierały się właściwe panele.
   - Menu `Edycja` udostępnia operacje schowka, `Alt+↑/↓` przenosi pozycje.
   - Playlisty newsowe mają przyciski „Wczytaj serwis…” / „Zapisz serwis…” (oraz skróty `Ctrl+O` / `Ctrl+S`) działające na plikach `.saranews`. Ten sam format obsługuje niezależna aplikacja `sara-news-editor`, która zapamiętuje ostatnio użyte urządzenie, pozwala wybrać kartę audio i odsłuchiwać klipy bez uruchamiania całej Sary.
   - `Ctrl+E` przełącza tryb edycji i odczytu; w trybie odczytu `H`/`Shift+H` skacze po nagłówkach, `C`/`Shift+C` po klipach, a Tab przenosi fokus na pasek narzędzi (w tym długość linii i urządzenie audio).

Konfiguracja trafia do `config/settings.yaml`, ale wygodniej edytować ją z poziomu okna „Opcje…”. Pamiętaj o licencjach BASS przy użyciu komercyjnym.

### Lokalne sterowanie TCP

Serwer `127.0.0.1:51443` pozwala sterować emisją z mostka MR18/X-TOUCH bez aktywowania okna SARY. Jest domyślnie włączony. Wyłączenie i zmianę portu udostępnia zakładka „Zdalne sterowanie” w Opcjach. [Opis protokołu i ustawień](docs/sterowanie-tcp.md) obejmuje również różnice względem StationPlaylist, w tym Pause, które tylko wstrzymuje odtwarzanie.

### Testy
```
PYTHONPATH=src python -m pytest
```
Testy UI/E2E na Windows (opcjonalnie): `RUN_SARA_E2E=1 PYTHONPATH=src python -m pytest -m e2e tests/e2e` (mock audio, izolowana konfiguracja przez `SARA_CONFIG_DIR`).

### Struktura katalogów
```
./docs           # dokumentacja i notatki
./src/sara       # źródła aplikacji
./tests          # testy jednostkowe/integracyjne
```

### Funkcje
- Wiele playlist z niezależnymi slotami i przypisaniem urządzeń WASAPI/ASIO.
- Strumieniowe odtwarzanie (sounddevice/pycaw/pythonnet) z ReplayGain.
- Rozbudowane sterowanie klawiaturą i operacje schowka.
- Dialog pętli z odsłuchem PFL oraz zapisem w tagach.
- Dokładne zapętlanie intra w odtwarzaczu BASS.
- Playlisty newsowe z edycją Markdown, trybem tylko do odczytu i przyciskami audio.
- Playlisty folderów muzycznych: wskaż katalog, odsłuchuj na PFL klawiszem `Spacja`, a `Enter` dodaje zaznaczone utwory do bieżącej playlisty muzycznej.
- Import/eksport plików `.saranews` oraz niezależny News Editor (`sara-news-editor`) z zapamiętywaniem urządzenia audio do przygotowywania serwisów.
- Opcje: fade, PFL, playlisty startowe, język interfejsu, tryb naprzemienny, auto-usuwanie.
- Komunikaty dostępności (NVDA) i testy pokrywające kluczowe moduły.

#### Playlisty newsowe – szczegóły
- **Tryb edycji (`Ctrl+E`):** zwykły edytor Markdown z wklejaniem `Ctrl+V` (pliki/foldery lub tokeny `[[audio:ścieżka]]`). Paski „Wczytaj/Zapisz/Wstaw audio” obsługują format `.saranews`.
- **Tryb tylko do odczytu (`Ctrl+E` ponownie):** tekst zawija się do zadanego limitu, `H`/`Shift+H` przechodzi po nagłówkach, `C`/`Shift+C` po klipach audio, `Enter`/`Spacja` odtwarza bieżący klip, a Tab przechodzi do paska narzędzi (w tym spinnera długości linii, przycisku Apply i wyboru urządzenia).
- **Samodzielny edytor (`sara-news-editor`):** korzysta z tego samego panelu, zapisuje konfigurację w `config/news_editor.yaml` obok aplikacji, pamięta ostatnie urządzenie audio i pozwala przygotować serwis bez uruchamiania głównej Sary.

### Pakowanie i dystrybucja
- Dopilnuj, by pliki lokalizacyjne i binaria NVDA/BASS trafiały do pakietu (zob. `MANIFEST.in`, `pyproject.toml`).
- Zbuduj paczki poleceniem `python -m build`; po instalacji dostępny jest skrypt `sara` uruchamiający GUI.
- Tworząc wersję Windows (np. PyInstaller), dołącz biblioteki NVDA oraz ewentualne biblioteki BASS obok pliku wykonywalnego.
- Paczka Windows zawiera teraz zarówno `SARA.exe`, jak i `SARA-News-Editor.exe`, korzystające ze wspólnych bibliotek i dll-i NVDA/BASS.
- GitHub Actions udostępnia workflow **Windows Build**, który na każdym pushu do `main` (oraz przy wydaniu) buduje paczkę `.zip` z katalogiem `dist/SARA` gotowym do pobrania.
- Pakiet z CI zawiera biblioteki NVDA oraz `bass.dll` dla Windows, więc mowa i opcjonalne odtwarzanie BASS działają od razu.

### Plany
- Rozbudowa komunikatów dostępności.
- Persistencja dodatkowych parametrów utworu.
- Zaawansowane crossfade i planowanie emisji.
- Osobne buforowanie dla głównych odtwarzaczy i PFL.
- Edytor punktów intro/outro zgodny z tagami StationPlaylist.
- Wypowiadanie pozostałego czasu intra i skrót odczytujący czas do końca utworu.
- Playlista nakładkowa, która odtwarza bez wygaszania pozostałych playlist.
- Automatyczne pobieranie najnowszego buildu (skrypt + hooki git).
- Granulacja komunikatów dostępności.
- Wstępne ładowanie utworów do pamięci w celu ograniczenia opóźnień dyskowych.

### Licencja
- Kod aplikacji: BSD 3-Clause (`LICENSE`).
- Biblioteki BASS: zgodnie z licencją Un4seen (`src/sara/audio/vendor/bass.txt`).
- Dołączone biblioteki NVDA Controller podlegają [licencji NV Access](https://www.nvaccess.org/about-nvda/license-and-credits/).
