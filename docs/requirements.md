# Wymagania programu emisyjnego

## Kontekst
System ma służyć do emisji muzyki w stacjach radiowych. Kluczowe elementy to obsługa wielu playlist, niezależne ścieżki wyjściowe audio (WASAPI/ASIO) oraz w pełni dostępny interfejs użytkownika oparty o wxPython.

## Założenia funkcjonalne
- **Główne okno**: prezentuje listę playlist zdefiniowanych przez użytkownika.
- **Playlisty**: 
  - każda zawiera uporządkowaną listę plików audio;
  - możliwość dodawania, usuwania i reorganizowania utworów;
  - oznaczanie utworów odegranych.
  - prezentacja postępu odtwarzania (czas bieżący vs. całkowity).
- **Sterowanie**:
  - globalne skróty klawiszowe (np. spacja) odtwarzające kolejny utwór (kolejność: 1. utwór 1. playlisty, 1. utwór 2. playlisty, itd.);
  - indywidualne skróty dla każdej playlisty (play/pause, stop, fade), najlepiej konfigurowalne przez użytkownika;
  - menu kontekstowe/akcyjne dostępne przez klawisz Alt (integracja z menu systemowym wx).
- **Audio**:
  - możliwość przypisania playlisty do konkretnego wyjścia audio (urządzenie WASAPI lub ASIO);
  - obsługa fade in/fade out, crossfade (rozszerzenie w kolejnych etapach);
  - monitoring stanu odtwarzania (aktualny poziom, czas pozostały).
  - player przekazuje zdarzenia postępu i zakończenia do UI (callbacki zamiast pollingów).
- **Dostępność**:
  - pełna obsługa klawiaturą;
  - etykiety i role dostępne dla czytników ekranu (wx.Accessible, aria role, focus management);
  - komunikaty stanu (np. rozpoczęcie/koniec odtwarzania) jako powiadomienia tekstowe/log.

## Założenia niefunkcjonalne
- Implementacja w Pythonie (3.11+).
- Interfejs użytkownika w oparciu o wxPython (Phoenix).
- Architektura modułowa z warstwami: GUI, logika biznesowa, silnik audio.
- Możliwość pracy offline (brak wymaganej sieci).
- Łatwość rozszerzania (pluginy/scripting w przyszłości).

## Integracje i biblioteki planowane
- `wxPython` (GUI + dostępność).
- `sounddevice` lub `pyasio`/`pythonnet` dla ASIO; `pycaw`/`comtypes` dla WASAPI.
- `watchdog` (opcjonalnie) do nasłuchiwania zmian w folderach z plikami.
- `sqlalchemy`/`sqlite` dla przechowywania konfiguracji (opcjonalnie w kolejnych iteracjach).

## Otwarte pytania
1. Preferowany format konfiguracji (pliki JSON/YAML vs. baza danych)?
2. Czy odtwarzanie ma wspierać dodatkowe efekty (crossfade, ducking, jingles)?
3. Jakie formaty plików audio są najczęściej stosowane (WAV, MP3, FLAC)?
4. Czy wymagane jest monitorowanie i logowanie emisji (raporty)?
5. Czy ma istnieć możliwość sterowania zdalnego (np. HTTP API)?

## Etapy realizacji
1. **Analiza i projekt**: dopracowanie wymagań, przygotowanie makiet UI.
2. **Szkielet aplikacji**: struktura projektu, podstawowe okno wx, logowanie zdarzeń.
3. **Warstwa audio**: integracja z WASAPI/ASIO, abstrakcja urządzeń, testy jednostkowe.
4. **Zarządzanie playlistami**: CRUD, oznaczanie utworów, kolejka emisji, skróty.
5. **Dostępność i ergonomia**: audyty, dostosowanie dla czytników ekranu, personalizacja skrótów.
6. **Stabilizacja**: testy end-to-end, pakiet instalacyjny, dokumentacja.
