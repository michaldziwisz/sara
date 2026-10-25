# Automatyczne wyrównywanie głośności

W Narzędzia → Opcje → Ogólne znajduje się domyślnie zaznaczone pole „Automatycznie wyrównuj głośność nowych utworów do EBU R128 (-23 LUFS)”. Po dodaniu plików do playlisty muzycznej SARA mierzy je kolejno w tle. Dotyczy to także folderów, schowka, playlist M3U i playlist otwieranych przy uruchomieniu. Playlisty tekstowe i jingle nie są automatycznie mierzone. Pomiar nie wywołuje komunikatu mowy po każdym utworze.

SARA dąży do głośności -23 LUFS. Ogranicza jednak podbicie tak, aby oszacowany szczyt rzeczywisty po wzmocnieniu nie przekraczał -1 dBTP. Przykładowo utwór o głośności -30 LUFS i szczycie -2 dBTP dostanie +1 dB, a nie +7 dB. Dlatego niektóre nagrania pozostaną cichsze od poziomu docelowego. Jest to wybór stałego wzmocnienia dla całego utworu, nie kompresor ani dynamiczny limiter.

Wzmocnienie mieści się w zakresie obsługiwanym przez odtwarzacz, od -60 do +18 dB. Jest zapisywane jako tag APEv2 `REPLAYGAIN_TRACK_GAIN`. Razem z nim powstaje znacznik `SARA_LOUDNESS` zawierający standard, zmierzoną głośność, true peak, cel i zastosowane wzmocnienie. SARA nie zmienia próbek nagrania. Pliku ze znacznikiem nie mierzy ponownie, także po ponownym uruchomieniu. Sam ReplayGain zapisany przez inny program nie zastępuje tego znacznika: taki plik zostanie zmierzony raz i otrzyma wynik SARY.

Utwór, który już gra, zachowuje dotychczasowe wzmocnienie. Nowa wartość jest zapamiętywana w playliście i używana przy następnym starcie. Zapis tagów czeka, jeśli plik jest odtwarzany, wstrzymany, wstępnie załadowany albo trwa odsłuch PFL. Zamknięcie programu może pozostawić taki wynik tylko w pamięci; bez zapisanego znacznika plik zostanie zmierzony przy następnym wczytaniu.

Przycisk normalizacji w oknie punktów miksu korzysta z tego samego obliczenia i zapisuje ten sam rodzaj znacznika. Nadal można tam wybrać EBU R128 albo ATSC A/85, którego celem jest -24 LUFS. Oba warianty uwzględniają true peak.

Wyłączenie pola w Opcjach zatrzymuje rozpoczynanie kolejnych automatycznych pomiarów. Nie usuwa wcześniej zapisanych tagów ani wzmocnienia. Błąd analizatora lub zapisu jest odnotowywany w logu bez otwierania okna. Po błędzie zapisu wynik pozostaje w pamięci, a ponowne wczytanie pliku pozwala ponowić zapis. Brak narzędzia `bs1770gain` wyłącza automat na bieżącą sesję i daje jeden wpis w logu.
