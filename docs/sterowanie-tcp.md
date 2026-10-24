# Lokalne sterowanie TCP

SARA przyjmuje polecenia od mostka MR18/X-TOUCH i innych programów działających na tym samym komputerze. Okno SARY nie musi być na pierwszym planie. Serwer nie udostępnia odtwarzania innym komputerom ani przez Internet.

## Włączenie i port

W oknie Opcje, na zakładce „Zdalne sterowanie”, znajdują się:

* „Włącz lokalne sterowanie TCP (127.0.0.1)”, domyślnie zaznaczone;
* „Port sterowania TCP”, domyślnie 51443, zakres od 1 do 65535.

Zmiany obowiązują po zatwierdzeniu przyciskiem OK. Wyłączenie zamyka istniejące połączenia. Zmiana portu zamyka stary nasłuch i uruchamia nowy. Nie zmienia toru audio ani ustawień miksu. Zajęty port powoduje komunikat „Sterowanie zdalne niedostępne na porcie …” i wpis w logu; SARA nadal działa, ale nie przyjmuje poleceń TCP. Należy wybrać wolny port i ponownie zatwierdzić opcje.

Te same ustawienia są zapisywane w pliku konfiguracji SARY:

```yaml
remote:
  enabled: true
  port: 51443
```

Brak sekcji w starszej konfiguracji oznacza włączenie serwera na porcie 51443. Aby wyłączyć go przed uruchomieniem aplikacji, należy ustawić `enabled: false`. Nie ma ustawienia adresu nasłuchu: zawsze jest nim IPv4 `127.0.0.1`. W protokole nie ma hasła. Każdy proces na tym komputerze, który ma dostęp do tego adresu i portu, może sterować emisją. Nie należy przekierowywać portu do sieci.

## Połączenie i odpowiedzi

* TCP, kodowanie UTF-8, bez powitania wysyłanego automatycznie po połączeniu.
* Polecenie kończy LF albo CRLF. Odpowiedzi kończą się CRLF.
* Wielkość liter w nazwach poleceń nie ma znaczenia.
* Można wysłać `This,Rem,Stat` w jednej linii. Każde polecenie daje osobną odpowiedź.
* Poleceń z `=` nie wolno łączyć przecinkami. Cała taka linia zostaje odrzucona bez wykonania któregokolwiek polecenia.
* `TrackInfo` i `TrackInfoEx` zwracają po jednej linii na każdy żądany indeks, bez nagłówka ani dodatkowego znacznika końca. Zakres jest domknięty, liczba odpowiedzi wynosi `do - od + 1`. Przy błędzie jest jedna linia `ERR …`.
* Obsługiwanych jest do 16 równoczesnych klientów. Limit wejściowej linii to 4096 bajtów wraz z zakończeniem. Po 30 sekundach bez danych połączenie może zostać zamknięte. Klient powinien odpytywać stan albo ponownie się łączyć.
* Polecenia trafiają przez `wx.CallAfter` do głównego wątku GUI. Czas oczekiwania wynosi 2 sekundy. Polecenie, którego wykonanie jeszcze się nie rozpoczęło, jest po przekroczeniu limitu anulowane. Już rozpoczętej operacji nie można cofnąć; po `ERR timeout` należy odczytać stan zamiast automatycznie ponawiać Play lub CheckToggle.
* Zwykłe zapytania nie uruchamiają dodatkowych komunikatów głosowych. Polecenia sterujące używają dotychczasowych komunikatów odpowiednich skrótów.

## Polecenia

| Polecenie | Odpowiedź i działanie |
| --- | --- |
| `Helo` | `SARA vX.Y.Z`, np. `SARA v0.0.37`. |
| `Stat` | Siedem cyfr opisanych poniżej. |
| `Play`, `Skip` | Dotychczasowa akcja globalnego „Odtwórz następny”, z zachowaniem automiksu, kolejki i naprzemiennego wyboru playlist. Odpowiedź: siedmiocyfrowy stan. |
| `Stop` | Dotychczasowa akcja zakończenia utworu z wyciszeniem, domyślnie F4. Czas wyciszenia oblicza istniejący kontroler. Odpowiedź: stan. |
| `Instant Stop` | Dotychczasowa akcja zatrzymania bez wyciszenia, domyślnie F3. Odpowiedź: stan. |
| `Pause` | Wstrzymanie jak F2. Kolejne Pause nie wznawia utworu i nie ogłasza ponownie pauzy. Odpowiedź: stan. |
| `AutoOn`, `AutoOff`, `Auto` | Włączenie, wyłączenie lub przełączenie automiksu przez istniejący kontroler. Włączenie może rozpocząć odtwarzanie jak skrót w SARZE. Odpowiedź: stan. |
| `This` | `artist - title` bieżącego utworu muzycznego, sam tytuł bez wykonawcy, pusta linia bez odtwarzania. Podczas pauzy nadal zwraca tytuł. |
| `Next` | Kandydat do następnego uruchomienia, z uwzględnieniem kolejki, automiksu i naprzemiennych playlist. Zapytanie nie konsumuje kolejki. Nie sprawdza dostępności pliku ani urządzenia audio. |
| `Rem`, `Elap` | Pozostały i upłynięty czas bieżącego utworu w milisekundach, `0` bez odtwarzania. Wartości z postępu odtwarzania, względem cue, do końca efektywnej długości utworu, a nie do punktu miksu. Nie odliczają czasu zegarowego podczas pauzy. |
| `SelectIndex` | Indeks podświetlonego wiersza albo `-1`. Nie jest to znacznik „do emisji”. |
| `SelectIndex=n` | Podświetlenie wiersza o indeksie n; odpowiedź: wybrany indeks. Nie rozpoczyna odtwarzania. |
| `SelectIndex=+`, `SelectIndex=-` | Przejście o jeden wiersz, bez zawijania na granicach. Bez wcześniejszego wskazania wybiera pierwszy wiersz. Zmienia fokus wiersza, nie aktywuje okna SARY. |
| `CurrIndex` | Indeks bieżącego utworu w aktywnej playliście muzycznej; `-1`, jeżeli brak bieżącego utworu w tej playliście. |
| `LastIndex` | Ostatni indeks aktywnej playlisty, `-1` dla pustej lub nieobecnej. |
| `CheckToggle` | Przełączenie „do emisji” wskazanego wiersza przez ten sam kontroler co klawiatura i menu kontekstowe. Odpowiedź: aktualny znacznik `0` lub `1`, `-1` bez wiersza. Przy automiksie zmiana jest blokowana z dotychczasowym komunikatem SARY. |
| `TrackInfo=od-do` | Wiersze CSV opisane poniżej. |
| `TrackInfoEx=od-do` | Rozszerzenie SARY, wiersze rozdzielane znakiem `|`. |

Indeksy zaczynają się od 0, oznaczającego pierwszy element aktywnej playlisty muzycznej. Nie obejmują folderów muzycznych ani serwisów informacyjnych. Jeżeli aktywny panel nie jest playlistą muzyczną, polecenia wymagające takiej playlisty nie wybierają samodzielnie innego panelu. Do sterowania należy wcześniej wybrać odpowiednią playlistę w SARZE; później można przejść do innej aplikacji.

`This` oraz czasy dotyczą najnowszego bieżącego utworu muzycznego z kontekstów odtwarzania. Wybór jest zgodny z kluczem NowPlaying, jeśli nadal jest aktywny; nie wymaga włączenia zapisu pliku NowPlaying. Przy jednoczesnym odtwarzaniu z kilku playlist `CurrIndex` może wynosić `-1`, jeśli utwór należy do innej playlisty niż aktywna.

## Stat

Cyfry, w kolejności od lewej:

1. Odtwarzany jest utwór muzyczny, który nie jest wstrzymany.
2. Automiks jest włączony.
3. Mikrofon: zawsze `0`.
4. Line-in: zawsze `0`.
5. Istnieje wstrzymany utwór muzyczny.
6. Gra dżingiel, także nakładany.
7. Stan modelu aktywnej playlisty różni się od zapamiętanego przy ostatnim `Stat` tego klienta.

Pierwsze `Stat` po połączeniu ma siódmą cyfrę `1`. Kolejne zapytanie bez zmian ma `0`. Porównanie obejmuje pozycje, kolejność, statusy, znaczniki do emisji, metadane, cue, pętle i break, ale nie sam postęp czasu ani samo podświetlenie wiersza. To porównanie migawek, nie dziennik każdej przejściowej edycji. Każde połączenie ma osobną migawkę. Odpowiedzi na polecenia sterujące nie zerują siódmej cyfry.

## TrackInfo i TrackInfoEx

`TrackInfo` ma dziesięć kolumn:

```text
Index,TrackType,Artist,Title,Album,Duration,IntroTime,OutroTime,Category,Filename
```

`TrackType`: 0 dla piosenki, 1 dla spotu. Album i Category są puste, ponieważ model playlisty SARY ich nie przechowuje. Wszystkie trzy pola czasu są liczbami milisekund; Duration to efektywna długość po odjęciu cue. Pola z przecinkiem lub cudzysłowem są cytowane według CSV. Znaki końca linii w metadanych zastępowane są spacjami.

`TrackInfoEx` ma siedem pól:

```text
Index|Checked|Status|Artist|Title|DurationMs|BreakAfter
0|1|pending|Wykonawca|Tytuł|180000|0
```

Checked i BreakAfter przyjmują `0` albo `1`. Status jest niezależny od języka interfejsu: `pending`, `playing`, `paused` albo `played`. DurationMs jest efektywną długością po odjęciu cue. Znaki `|`, CR, LF oraz NUL w metadanych zastępowane są spacjami, aby nie zmieniały liczby pól lub linii.

## Błędy

* `ERR unknown`: nieznane polecenie; nigdy nie uruchamia skryptu ani programu.
* `ERR syntax`: niepoprawna składnia lub niedozwolone łączenie poleceń z `=`.
* `ERR range`: nieistniejący indeks albo niepoprawny zakres. Zakresy nie są po cichu przycinane.
* `ERR timeout`: brak wyniku z wątku GUI w wymaganym czasie.
* `ERR closed`: serwer jest wyłączany.
* `ERR internal`: błąd wykonania, szczegóły w logu SARY.
* `ERR encoding`: wejście nie jest poprawnym UTF-8.
* `ERR line too long`: przekroczono limit linii, po czym połączenie jest zamykane.

## Zgodność ze StationPlaylist Studio Pro

Nazwy poleceń i ramkowanie odpowiadają podzbiorowi opisanemu w pomocy SPLStudio.chm, w rozdziałach `opt_comms.html` i `opt_commtcp.html`. Nie jest to pełna emulacja SPL.

Ważne różnice:

* W SPL `Pause` przełącza pauzę i wznowienie. W SARZE tylko wstrzymuje, dokładnie jak F2. Mostek MR18 nie musi korzystać z Pause.
* Play i Skip w SARZE są tą samą istniejącą akcją „Odtwórz następny”. Stop i Instant Stop dotyczą aktywnej playlisty, tak jak skróty SARY, a nie globalnego zatrzymania wszystkich dżingli i playlist.
* Automatyka oznacza automiks SARY, mikrofon i line-in nie są sterowane.
* Indeks 0 oznacza pierwszy utwór, nie znacznik godziny SPL.
* TrackInfo obsługuje zakres liczbowy, nie warianty `this`, `next` i `all`.
* TrackInfoEx jest rozszerzeniem SARY. Klient powinien wykryć prefiks `SARA` przez Helo przed jego użyciem.
* Nieznane polecenia nie są interpretowane jako nazwy skryptów. Klient SPL powinien wysyłać wyłącznie rozpoznane polecenia.

## Sprawdzenie połączenia

Przykład do uruchomienia w Pythonie na tym samym komputerze co SARA. Nie zmienia odtwarzania:

```python
import socket

with socket.create_connection(("127.0.0.1", 51443), timeout=3) as connection:
    connection.sendall(b"Helo,This,Rem,Stat\r\n")
    with connection.makefile("rb") as response:
        for _ in range(4):
            print(response.readline().decode("utf-8").rstrip("\r\n"))
```

Do odczytania listy należy najpierw pobrać LastIndex, a następnie wysłać osobną linię `TrackInfoEx=0-n`. Przy `-1` nie ma pozycji do pobrania.
