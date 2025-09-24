# SARA (Simple Accessible Radio Automation)

SARA is a wxPython-based automation suite for radio stations. It provides multiple playlists, independent audio outputs (WASAPI/ASIO), extensive keyboard control, and screen-reader friendly UI.

---

## 🇬🇧 English
### Status
*Work in progress* – playback, multiple players per playlist, and loop tools are functional.

### Quick start
1. Install system prerequisites (wxWidgets, audio backends such as WASAPI/ASIO where required).
2. Optionally download [BASS](https://www.un4seen.com/) and place `bass.dll` next to the project (or set `BASS_LIBRARY_PATH`).
3. Create a virtualenv for Python 3.11+: `python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`).
4. Install dependencies: `pip install -r requirements-dev.txt`.
5. Run the app: `python -m sara.app`.
6. In the UI:
   - Add a playlist (`Ctrl+N`).
   - Add tracks (`Ctrl+D`).
   - Map players/devices (`Ctrl+Shift+D`).
   - Set a marker with `Enter` and toggle marker mode (`Ctrl+Shift+Enter`) so global `Space` starts from it.
   - Playlist controls: `F1` play, `F2` pause, `F3` stop, `F4` fade out, `Ctrl+Shift+L` toggle loop, `Ctrl+Shift+M` auto-mix.
   - Loop dialog (`Shift+F10 → Loop…`): fine-tune start/end, capture preview (`Ctrl+P` / `Ctrl+Shift+P`). Loop ranges are saved in APEv2 tags (`SARA_LOOP_*`).
   - Use `Ctrl+Alt+L` to toggle looping per track; `Ctrl+Alt+Shift+L` announces loop info.
   - Options (`Tools → Options…`) let you adjust fade out, PFL device, startup playlists, alternate play mode and auto removal of played tracks.
   - Edit menu provides standard clipboard actions, move items with `Alt+↑/↓`.

Configuration is stored in `config/settings.yaml`, but editing through the Options dialog is recommended. Bundled BASS binaries (Windows/Linux) are provided for convenience; commercial usage requires a license from Un4seen.

### Tests
```
PYTHONPATH=src python -m pytest
```

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
- Options dialog for fade, PFL device, startup playlists, language, alternate play, auto-remove.
- Screen-reader announcements (NVDA) and coverage in the test suite.

### Packaging & release
- Ensure locale and vendor binaries are included (`MANIFEST.in`, `pyproject.toml`).
- Build distributables with `python -m build`; the `sara` console entry starts the GUI.
- For frozen Windows builds, bundle NVDA controller DLLs and optional BASS binaries alongside the executable.

### Roadmap highlights
- Enhanced accessibility messages.
- Persisting extra track parameters.
- Advanced fade/crossfade scenarios and scheduling.

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
3. Utwórz wirtualne środowisko Python 3.11+: `python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`).
4. Zainstaluj zależności projektu: `pip install -r requirements-dev.txt`.
5. Uruchom aplikację: `python -m sara.app`.
6. W interfejsie:
   - Dodaj playlistę (`Ctrl+N`).
   - Dodaj utwory (`Ctrl+D`).
   - Przypisz odtwarzacze/urządzenia (`Ctrl+Shift+D`).
   - Ustaw znacznik klawiszem `Enter`, a tryb od znacznika (`Ctrl+Shift+Enter`) sprawi, że Spacja startuje od niego.
   - Sterowanie playlistą: `F1` – start, `F2` – pauza, `F3` – stop, `F4` – fade out, `Ctrl+Shift+L` – pętla, `Ctrl+Shift+M` – auto mix.
   - Dialog pętli (`Shift+F10 → Zapętl…`): precyzyjne start/koniec, odsłuch PFL (`Ctrl+P` / `Ctrl+Shift+P`). Pętle zapisują się w tagach APEv2.
   - Przełączanie zapętlenia utworu (`Ctrl+Alt+L`) i informacja o pętli (`Ctrl+Alt+Shift+L`).
   - `Narzędzia → Opcje…` udostępniają sterowanie fade, urządzeniem PFL, playlistami startowymi, językiem, trybem naprzemiennym i auto-usuwaniem.
   - Menu `Edycja` udostępnia operacje schowka, `Alt+↑/↓` przenosi pozycje.

Konfiguracja trafia do `config/settings.yaml`, ale wygodniej edytować ją z poziomu okna „Opcje…”. Pamiętaj o licencjach BASS przy użyciu komercyjnym.

### Testy
```
PYTHONPATH=src python -m pytest
```

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
- Opcje: fade, PFL, playlisty startowe, język interfejsu, tryb naprzemienny, auto-usuwanie.
- Komunikaty dostępności (NVDA) i testy pokrywające kluczowe moduły.

### Pakowanie i dystrybucja
- Dopilnuj, by pliki lokalizacyjne i binaria NVDA/BASS trafiały do pakietu (zob. `MANIFEST.in`, `pyproject.toml`).
- Zbuduj paczki poleceniem `python -m build`; po instalacji dostępny jest skrypt `sara` uruchamiający GUI.
- Tworząc wersję Windows (np. PyInstaller), dołącz biblioteki NVDA oraz ewentualne biblioteki BASS obok pliku wykonywalnego.

### Plany
- Rozbudowa komunikatów dostępności.
- Persistencja dodatkowych parametrów utworu.
- Zaawansowane crossfade i planowanie emisji.

### Licencja
- Kod aplikacji: BSD 3-Clause (`LICENSE`).
- Biblioteki BASS: zgodnie z licencją Un4seen (`src/sara/audio/vendor/bass.txt`).
- Dołączone biblioteki NVDA Controller podlegają [licencji NV Access](https://www.nvaccess.org/about-nvda/license-and-credits/).
