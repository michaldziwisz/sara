# Lokalne sterowanie TCP

SARA przyjmuje polecenia od mostka MR18/X-TOUCH i innych programów działających na tym samym komputerze. Okno SARY nie musi być na pierwszym planie. Serwer nie udostępnia odtwarzania innym komputerom ani przez Internet.

## Włączenie i port

W oknie Opcje, na zakładce „Zdalne sterowanie”, znajdują się:

* „Włącz lokalne sterowanie TCP (127.0.0.1)”, domyślnie zaznaczone;
* „Port sterowania TCP”, domyślnie 51443, zakres od 1 do 65535;
* „Główna playlista muzyczna”, domyślnie „Pierwsza muzyczna”. Lista zawiera nazwy otwartych playlist muzycznych, bez folderów i wiadomości.

Zmiany obowiązują po zatwierdzeniu przyciskiem OK. Wyłączenie zamyka istniejące połączenia. Zmiana portu zamyka stary nasłuch i uruchamia nowy. Nie zmienia toru audio ani ustawień miksu. Zajęty port powoduje komunikat „Sterowanie zdalne niedostępne na porcie …” i wpis w logu; SARA nadal działa, ale nie przyjmuje poleceń TCP. Należy wybrać wolny port i ponownie zatwierdzić opcje.

Te same ustawienia są zapisywane w pliku konfiguracji SARY:

```yaml
remote:
  enabled: true
  port: 51443
  main_playlist: ""
```

Brak sekcji w starszej konfiguracji oznacza włączenie serwera na porcie 51443. Aby wyłączyć go przed uruchomieniem aplikacji, należy ustawić `enabled: false`. Nie ma ustawienia adresu nasłuchu: zawsze jest nim IPv4 `127.0.0.1`. W protokole nie ma hasła. Każdy proces na tym komputerze, który ma dostęp do tego adresu i portu, może sterować emisją. Nie należy przekierowywać portu do sieci.

## Główna playlista i klawiatura

Stół steruje główną playlistą muzyczną wybraną w Opcjach. Puste `remote.main_playlist` oznacza pierwszą muzyczną w kolejności układu. Niepuste pole przechowuje identyfikator, nie nazwę playlisty. Jeżeli identyfikator już nie istnieje albo wskazuje inny rodzaj panelu, celem znów jest pierwsza muzyczna. Bez żadnej muzycznej odczyty indeksów zwracają `-1`, tytuł jest pusty, a Play niczego nie uruchamia.

Można czytać wiadomości, mieć fokus na ich przycisku „Zapisz” albo pracować w innej aplikacji. Zdalne Play uruchamia muzyczną część akcji „Odtwórz następny”, nie naciska przycisku wiadomości. Polecenia nie aktywują okna ani playlisty i nie przenoszą fokusu klawiatury. Zmieniać może się wskazany wiersz głównej playlisty.

Skróty klawiaturowe w SARZE pozostają bez zmian: działają na aktywnym panelu. Główna playlista nie zastępuje go dla Spacji, F1–F4 ani Ctrl+B. Włączony tryb naprzemiennego odtwarzania nadal stosuje dotychczasową kolejność dla Play, Skip i Next; również wtedy polecenie stołu nie przełącza aktywnego panelu. Automiks pozostaje globalnym trybem SARY, ale AutoOn rozpoczyna odtwarzanie na głównej, nie na aktywnej playliście.

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
| `Play` | W trybie ręcznym działa jak Enter na głównej playliście: gdy są zaznaczone utwory, gra pierwszy z kolejki (kolejne po nim, po kolei), a bez kolejki gra podświetlony utwór. Podświetlony utwór, który już gra, nie jest uruchamiany od nowa. Bez podświetlenia, w automiksie i przy naprzemiennych playlistach: muzyczna część akcji „Odtwórz następny”. Odpowiedź: siedmiocyfrowy stan. |
| `Skip` | Muzyczna część akcji „Odtwórz następny” na głównej playliście, z zachowaniem automiksu, kolejki i naprzemiennego wyboru playlist. Odpowiedź: siedmiocyfrowy stan. |
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
| `CurrIndex` | Indeks bieżącego utworu w głównej playliście muzycznej; `-1`, jeżeli brak bieżącego utworu w tej playliście. |
| `LastIndex` | Ostatni indeks głównej playlisty, `-1` dla pustej lub nieobecnej. |
| `CheckToggle` | Przełączenie „do emisji” wskazanego wiersza przez ten sam kontroler co klawiatura i menu kontekstowe. Odpowiedź: aktualny znacznik `0` lub `1`, `-1` bez wiersza. Przy automiksie zmiana jest blokowana z dotychczasowym komunikatem SARY. |
| `TrackInfo=od-do` | Wiersze CSV opisane poniżej. |
| `TrackInfoEx=od-do` | Rozszerzenie SARY, wiersze rozdzielane znakiem `|`. |
| `Hold`, `Hold=1`, `Hold=0` | Odczyt, włączenie lub zwolnienie wstrzymania automatycznego startu na głównej playliście. Odpowiedź: `0` albo `1`, przecinek i stan opisany poniżej. |

Indeksy zaczynają się od 0, oznaczającego pierwszy element głównej playlisty muzycznej. Nie obejmują folderów muzycznych ani serwisów informacyjnych. Wybór głównej nie zależy od fokusu ani aktywnego panelu.

`This` oraz czasy dotyczą bieżącego utworu wyłącznie z głównej playlisty. Klucz NowPlaying jest uwzględniany tylko wtedy, gdy należy do niej; w przeciwnym razie wybierany jest jej najnowszy kontekst. Nie wymaga to włączenia zapisu pliku NowPlaying. Odtwarzanie z innej playlisty nie zmienia This, CurrIndex ani czasów głównej.

## Stat

Cyfry, w kolejności od lewej:

1. Na głównej playliście odtwarzany jest utwór, który nie jest wstrzymany.
2. Automiks jest włączony.
3. Mikrofon: zawsze `0`.
4. Line-in: zawsze `0`.
5. Na głównej playliście istnieje wstrzymany utwór muzyczny.
6. Gra dżingiel, także nakładany.
7. Stan modelu głównej playlisty różni się od zapamiętanego przy ostatnim `Stat` tego klienta.

Pierwsze `Stat` po połączeniu ma siódmą cyfrę `1`. Kolejne zapytanie bez zmian ma `0`. Porównanie obejmuje pozycje, kolejność, statusy, znaczniki do emisji, metadane, cue, pętle i break, ale nie sam postęp czasu ani samo podświetlenie wiersza. To porównanie migawek, nie dziennik każdej przejściowej edycji. Każde połączenie ma osobną migawkę. Odpowiedzi na polecenia sterujące nie zerują siódmej cyfry.

## Hold: mikrofon wstrzymuje automat

`Hold=1` pozwala bieżącemu utworowi grać do końca, ale blokuje automatyczny start kolejnego. Działa zarówno w automiksie, jak i przy kolejce utworów zaznaczonych do emisji. Nie wycisza, nie pauzuje i nie steruje fizycznym mikrofonem. Mostek wysyła `Hold=1` po otwarciu mikrofonu, a `Hold=0` po jego zamknięciu.

Odpowiedź jest zawsze pojedynczą linią `<0|1>,<stan>`. Pierwsze pole określa, czy wstrzymanie jest włączone:

| Stan | Znaczenie |
| --- | --- |
| `brak` | Nic nie gra na głównej. Tak odpowiada także Hold=0 po zakończeniu utworu. |
| `trzyma` | Utwór ma kontekst odtwarzania. Przy `1` po nim nastąpi cisza; przy `0` oznacza po prostu „gra”, również jeśli jest zapauzowany. |
| `zatrzymane` | Utwór skończył się podczas wstrzymania, a playlista stoi po przerwie. |
| `za_pozno` | Wstrzymanie jest włączone, ale trwa już przejście z co najmniej dwoma kontekstami głównej. Nic nie zostaje ucięte; przerwę dostaje utwór wchodzący. |

Wstrzymanie używa tego samego mechanizmu „przerwa po utworze” co Ctrl+B: zdejmuje wyzwalacz miksu i oznacza przerwę. Zapamiętuje tylko własne przerwy. Ręczna przerwa ustawiona wcześniej przez użytkownika zostaje zachowana po Hold=0.

Zwolnienie podczas odtwarzania usuwa tylko przerwy ze stołu i przywraca wyzwalacz zgodnie z aktualnymi punktami miksu, jak Ctrl+B. Jeżeli utwór zdążył się skończyć, Hold=0 niczego nie uruchamia. Play lub Następny rozpoczyna od pozycji zachowanej po przerwie.

Przykłady kolejnych, osobnych linii poleceń i odpowiedzi:

| Polecenie | Przykładowa odpowiedź | Sytuacja |
| --- | --- | --- |
| `Hold=1` | `1,trzyma` | Mikrofon otwarty, bieżący utwór gra dalej. |
| `Hold=1` | `1,trzyma` | Powtórzenie nie zdejmuje przerwy ani nie zmienia odtwarzania. |
| `Hold` | `1,zatrzymane` | Utwór skończony, następny czeka. |
| `Hold=0` | `0,brak` | Mikrofon zamknięty, nadal cisza. |
| `Play` | siedem cyfr Stat | Ręczny start następnego utworu. |
| `Hold=1` | `1,za_pozno` | Przejście już trwa; automat stanie po wchodzącym utworze. |
| `Hold=0` | `0,trzyma` | Zwolnienie przed końcem utworu, odtwarzanie trwa. |

Nowy utwór uruchomiony podczas Hold, także Spacją w SARZE, dostaje przerwę przez zegar wx co 100 ms. Każde polecenie sprawdza ją również przed i po wykonaniu. Nie jest to zegar czasu rzeczywistego: zablokowana pętla GUI opóźni zarówno obsługę TCP, jak i sprawdzenie zegara. SARA nie potrafi cofnąć przejścia, które już się rozpoczęło.

Stan Hold jest wspólny dla wszystkich klientów. Rozłączenie samego klienta nie zwalnia wstrzymania; mostek może połączyć się ponownie i powtórzyć Hold=1. Wyłączenie usługi, zmiana portu i zamknięcie SARY zwalniają Hold bez uruchamiania odtwarzania. Zmiana głównej playlisty podczas Hold przenosi ochronę na nową i sprząta własne przerwy na poprzedniej.

Inna wartość, np. `Hold=2`, daje `ERR syntax`. Nie wolno łączyć `Hold=1` ani `Hold=0` z innymi poleceniami przecinkiem. Sam odczyt można połączyć, np. `Hold,This`.

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
* Play i Skip w SARZE są tą samą istniejącą akcją „Odtwórz następny”. Stop i Instant Stop dotyczą głównej playlisty, a skróty SARY aktywnej, a nie globalnego zatrzymania wszystkich dżingli i playlist.
* Automatyka oznacza automiks SARY, mikrofon i line-in nie są sterowane.
* Indeks 0 oznacza pierwszy utwór, nie znacznik godziny SPL.
* TrackInfo obsługuje zakres liczbowy, nie warianty `this`, `next` i `all`.
* TrackInfoEx i Hold są rozszerzeniami SARY. Klient powinien wykryć prefiks `SARA` przez Helo przed ich użyciem.
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
