# Executor triggerów miksu (UI vs wątek)

Punkt miksu (segue/overlap/fade) może zostać wyzwolony:

- **native** (z backendu, np. BASS `SYNC_MIXTIME`) – precyzyjny czasowo,
- **fallback progresowy** – gdy brak native triggera albo backend „strzelił” zbyt wcześnie.

W przypadku native triggerów kluczowe jest, **jak szybko** aplikacja zareaguje na callback i wystartuje kolejny utwór.

## Dlaczego `ui` bywa problemem

Domyślnie SARA wykonywała miks przez `wx.CallAfter(...)`, czyli przez kolejkę zdarzeń UI. Gdy UI jest obciążone (np. odświeżenia list, NVDA, inne eventy), callback miksu może dostać dodatkowy lag.

## Opcja `thread`

Tryb `thread` przenosi wykonanie miksu do dedykowanego wątku roboczego:

- callback z backendu **tylko enqueue** (minimalny koszt w miejscu SYNC),
- start kolejnego utworu + fade-out bieżącego wykonywany jest poza pętlą wx,
- aktualizacje UI i tak wracają przez `wx.CallAfter` w istniejących callbackach progress/finished.

To ma na celu zmniejszenie odchyłek czasowych w okolicy miksu przy zachowaniu wx UI.

## Konfiguracja

W UI:
- `Tools → Options… → Playback → Mix trigger executor`

W pliku `config/settings.yaml`:
```yaml
playback:
  mix_executor: thread   # albo: ui
```

Override dla testów/diagnostyki:
- `SARA_MIX_EXECUTOR=ui|thread|rust|off`
  - `off` wyłącza native triggery (zostaje fallback progresowy).
  - `rust` używa natywnej biblioteki `sara_mix_executor.dll` (eksperymentalne).

Ścieżka do biblioteki (opcjonalnie, przydatne w dev/testach):
- `SARA_MIX_EXECUTOR_LIBRARY_PATH` – może wskazywać na plik `.dll` albo katalog z `.dll`.

## Metryki

W logach pojawia się linia `MIX_METRIC ...`, która raportuje opóźnienie między native callback a rozpoczęciem logiki miksu (pomocne do porównania `ui` vs `thread`).
