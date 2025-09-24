# Plan dostępności

1. **Nawigacja klawiaturą**
   - Wszystkie elementy interfejsu dostępne przez `Tab`/`Shift+Tab`.
   - Definicja skrótów konfigurowalnych w pliku preferencji.
2. **Role i opisy**
   - Uzupełnianie `Accessible` descriptions w wxPython, np. `wx.Accessible.SetName`.
   - Nazwy kolumn listy playlist dostosowane do czytników ekranu.
3. **Komunikaty statusu**
   - Każda akcja (start/stop/fade) generuje komunikat tekstowy w status barze.
   - Integracja z Speech API systemu (Windows Narrator) w późniejszej iteracji.
4. **Konfiguracja użytkownika**
   - Plik `config/accessibility.yaml` (planowany) pozwoli włączać/wyłączać komunikaty.
5. **Testy**
   - Scenariusze testowe z NVDA/JAWS (manualne) zapisane w dokumentacji QA.
