# Testowanie (headless-first)

Ten projekt jest rozwijany „na lata”, więc testy mają być:

- szybkie do uruchomienia lokalnie,
- możliwe do odpalenia bez uruchamiania GUI,
- odporne na refaktory (m.in. przenoszenie modułów z wrapperami).

## Szybkie komendy

### Testy headless (zalecane na co dzień)

```
PYTHONPATH=src venv_codex/bin/python -m pytest -q -m "not gui and not e2e"
```

### Testy GUI (opcja)

Wymagają wx i dostępnego displayu oraz jawnego opt-in:

```
WX_RUN_GUI_TESTS=1 PYTHONPATH=src venv_codex/bin/python -m pytest -q -m gui
```

### Testy E2E (opcja, Windows)

```
RUN_SARA_E2E=1 PYTHONPATH=src venv_codex/bin/python -m pytest -q -m e2e tests/e2e
```

## Zasady pisania testów „bez GUI”

1. Unikaj tworzenia `wx.App()` i okien/dialogów w testach jednostkowych.
2. Logikę testowalną przenoś do `sara.core` albo do helperów/kontrolerów UI, które nie wymagają realnego `wx` runtime.
3. Jeśli moduł potrzebuje typów z `wx`, używaj:
   - `TYPE_CHECKING` w kodzie produkcyjnym,
   - albo w testach stubbuj `wx` przez `sys.modules["wx"] = types.SimpleNamespace(...)` (patrz `tests/test_news_mode_controller.py`).
4. Testy, które realnie wymagają displayu, oznaczaj markerem `gui` i gatinguj env var (`WX_RUN_GUI_TESTS=1`).

