# Single-device mixer plan (PFL/main)

## Current
- Każdy utwór ma własny player (sounddevice/BASS); crossfade to dwa równoległe strumienie na jednym urządzeniu.
- Brak miejsca na soft-mix w jednym strumieniu; lekkie „kliknięcia” łagodzone tylko mini crossfade w SoundDevicePlayer.

## Cele
- Dla playlist z 1 slotem: jeden strumień na urządzenie, soft-mix wielu źródeł w buforze.
- Resampling wszystkich źródeł do native samplerate urządzenia.
- Mikro-fade + zero-crossing na mix-in/out, brak limitera (chyba że poziomy przesterują).
- Zostawić stary tryb multi-slot (osobne urządzenia) dla playlist z >1 slotem.

## Architektura
- `DeviceMixer` (na urządzenie):
  - utrzymuje `sd.OutputStream` (lub BASS player) o samplerate/channels urządzenia.
  - kolejka aktywnych źródeł `MixerSource` (id utworu, path, state, gain, loop info?).
  - kodowanie/odczyt pliku via soundfile; resampling do device rate (korzysta z `_resample_to_length`).
  - miks w callbacku: sumowanie bloków, stosowanie gain i małych fade’ów.
  - crossfade: start nowego źródła z fade-in, wygaszenie poprzedniego fade-out; zero-crossing snapping przy ustawianiu punktów mix-in/out (tolerancja kilka ms).
  - callbacki progress/finished per source, mapowane do PlaybackController.
- `PlaybackController`:
  - dla playlist 1-slotowych wywołuje `device_mixer.start_source(...)` zamiast `audio_engine.create_player`.
  - dla slotów >1 zachowuje obecny flow (player per slot/device).
  - mapowanie item_id -> source_id w mixerze; cleanup on stop/fadeout.

## Dygresje techniczne
- Wymusić wspólny samplerate = native device rate (z `sd.query_devices`); jeśli brak, fallback do pliku (jak dziś), ale mixer preferuje native.
- Mini crossfade: ~3–5 ms (configurable constant) w mixerze; zero-crossing: szukaj najbliższego crossing w oknie ±5 ms od punktu.
- Brak ogranicznika: mieszamy liniowo; w przyszłości opcjonalny soft clip/gain normalizer.

## Kroki implementacyjne
1) Wydzielić `DeviceMixer` (oddzielny moduł, np. `sara/audio/mixer.py`), testy unit na sztucznym `DummyOutputStream` + waveforms.
2) Rozszerzyć PlaybackController o ścieżkę „single-slot -> mixer”: start/stop, fade, progress/finish.
3) Dodać zero-crossing + mini fade do mixeru; użyć istniejącego resamplingu do device rate.
4) Integracja z PFL/news preview? (opcjonalnie: osobny mixer dla PFL device).
5) Testy: unit mixer, regresyjne na playback_controller (mock audio).
