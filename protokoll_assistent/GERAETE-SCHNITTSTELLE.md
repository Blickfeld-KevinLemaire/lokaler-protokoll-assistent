# Schnittstelle für Aufnahmegeräte (Version 1)

Über diese Schnittstelle laden die WLAN-Aufnahmegeräte (Firmware unter
`firmware/`) ihre Aufnahmen in die Protokoll-Software – in die
Windows-Anwendung **oder** in den Servermodus. Beide benutzen denselben Dienst
(`services/geraete_empfang_service.py`); dieses Dokument ist die verbindliche
Beschreibung für beide Seiten. Wer etwas am Ablauf ändert, ändert es hier, in
der Software und in der Firmware zusammen.

## Grundsätze

* **Aus, bis jemand ihn einschaltet.** Der Dienst öffnet nur dann einen Port,
  wenn er in den Einstellungen (Anwendung) bzw. mit `PROTOKOLL_EMPFANG=1`
  (Servermodus) eingeschaltet ist.
* **Jedes Gerät hat ein eigenes Token.** Die Software erzeugt es, zeigt es
  einmal an und speichert nur seinen SHA-256-Hash. Das Token bestimmt auch den
  Gerätenamen: Ein Gerät kann sich nicht als ein anderes ausgeben, und gleiche
  Dateinamen zweier Geräte kommen sich nicht in die Quere.
* **Nichts geht verloren.** Das Gerät löscht seine Kopie erst, wenn die
  Software `"fertig":true` meldet. Das meldet sie erst, nachdem Größe und
  Prüfsumme der ganzen Datei stimmen und die Datei vollständig auf der Platte
  liegt.
* **Abbrüche kosten nur das letzte Stück.** Hochgeladen wird in Teilen mit
  Byte-Versatz. Reißt die Verbindung ab, setzt das Gerät beim letzten
  bestätigten Byte wieder an – auch nach einem Neustart.
* **Wiederholungen schaden nicht.** Kommt dieselbe Aufnahme (gleiches Gerät,
  gleicher Name, gleiche Größe, gleiche Prüfsumme) ein zweites Mal an, legt die
  Software keine zweite Datei an und meldet trotzdem `fertig`.

Übertragen wird per HTTP im eigenen Netz. Das Token schützt davor, dass
Fremde Dateien einliefern oder den Dienst vortäuschen; **mitlesen** kann im
selben WLAN trotzdem, wer den Datenverkehr abgreift. Für fremde oder offene
Netze ist das nicht gedacht (siehe `SECURITY.md`).

## Allgemeines

* Adresse: `http://<Rechner>:<Port>`, Standardport **8765**.
* Jede Anfrage trägt `Authorization: Bearer <Token>`. Fehlt es oder ist es
  unbekannt: `401`. Die Software erzeugt Token mit 43 Zeichen aus
  `A–Z a–z 0–9 - _` (256 Bit Zufall); die Firmware nimmt 1–128 sichtbare
  ASCII-Zeichen ohne Leerzeichen an.
* Antworten sind JSON in **kompakter Schreibweise ohne Leerzeichen**
  (`{"naechstes_byte":0,"fertig":false}`), UTF-8,
  `Content-Type: application/json`. Die Firmware darf sich darauf verlassen und
  Felder per Textsuche lesen; die Reihenfolge der Felder ist nicht festgelegt.
* Fehlerantworten enthalten `"fehler":"<lesbarer Text>"`.
* Das Gerät schickt außerdem bei jeder Anfrage `X-Geraete-Id` (die
  Werks-MAC aus dem eFuse, 12 Hex-Zeichen klein, ohne Trenner, z. B.
  `1a2b3c4d5e6f`) und `X-Firmware` (`<Board>/<Version>`, z. B.
  `esp32-s3-audio/1.0.0`). Beides dient nur der Zuordnung und Fehlersuche –
  die Software merkt sich, welches Gerät mit welcher Firmware zuletzt von wo
  kam. Angemeldet wird ausschließlich über das Token; fehlen die Kopfzeilen,
  wird die Anfrage trotzdem angenommen.
* Dateinamen: Buchstaben, Ziffern, `_` und `-` (nur ASCII), höchstens 64
  Zeichen **vor** der Endung, dann eine Endung aus `.opus`, `.ogg`, `.wav`,
  `.mp3` (z. B. `H5_007.opus`; die Software nimmt die Endung auch groß
  geschrieben an). Anderes: `400`.

## Aufrufe

### `GET /api/v1/hallo`

Ist die Software erreichbar, und gilt das Token?

```json
{"dienst":"protokoll-assistent","schnittstelle":1,"geraet":"S3-Audio","teil_max_bytes":4194304}
```

Das Gerät wertet ein Ziel nur dann als erreichbar, wenn der Status `200` ist
**und** der Text `"dienst":"protokoll-assistent"` sowie `"schnittstelle":1`
enthält. Ein beliebiger Webserver, der `200` liefert, genügt also nicht.

### `GET /api/v1/aufnahmen/<Dateiname>`

Wie viel von dieser Aufnahme liegt schon vor?

```json
{"naechstes_byte":262144,"fertig":false}
```

`naechstes_byte` ist `0`, wenn nichts vorliegt. Eine schon abgeschlossene
Aufnahme gilt hier als „nichts liegt vor" – lädt das Gerät sie trotzdem noch
einmal hoch, erkennt die Software sie beim Abschluss (siehe oben).

### `PUT /api/v1/aufnahmen/<Dateiname>`

Hängt Bytes an.

| Kopfzeile | Pflicht | Bedeutung |
|---|---|---|
| `X-Offset` | ja | Byte, an dem dieses Stück beginnt. Muss genau `naechstes_byte` sein. |
| `Content-Length` | ja | Länge dieses Stücks, `0` bis `teil_max_bytes`. Chunked Transfer wird nicht angenommen (`411`). |
| `X-Gesamtgroesse` | nur beim Abschluss | Größe der ganzen Datei in Bytes |
| `X-SHA256` | nur beim Abschluss | SHA-256 der ganzen Datei, 64 Hex-Zeichen klein |

`X-Gesamtgroesse` und `X-SHA256` kommen immer **zusammen** und machen die
Anfrage zum Abschluss. Das abschließende Stück darf leer sein
(`Content-Length: 0`) – so kann das Gerät die Prüfsumme während des Sendens
berechnen und erst danach abschließen.

Antworten:

| Status | Wann | Text |
|---|---|---|
| `200` | Stück angehängt | `{"naechstes_byte":N,"fertig":false}` |
| `200` | Abschluss geprüft, Datei liegt vor | `{"naechstes_byte":N,"fertig":true,"datei":"S3-Audio_H5_007.opus"}` |
| `409` | `X-Offset` passt nicht | `{"naechstes_byte":N,"fertig":false,"fehler":"…"}` – ab `N` weitersenden |
| `422` | Größe oder Prüfsumme stimmt beim Abschluss nicht | `{"naechstes_byte":0,"fertig":false,"fehler":"…"}` – der Teilstand ist verworfen, von vorn beginnen |
| `400` | Kopfzeilen fehlen oder sind ungültig, Stück unvollständig angekommen | `{"fehler":"…"}` |
| `411` | keine `Content-Length` | `{"fehler":"…"}` |
| `413` | Stück größer als `teil_max_bytes` oder Datei größer als erlaubt | `{"fehler":"…"}` |
| `503` | zu viele gleichzeitige Verbindungen | `{"fehler":"…"}` – später erneut |
| `507` | zu wenig Platz auf der Platte | `{"fehler":"…"}` – später erneut |

Lehnt die Software ein Stück eines angemeldeten Geräts ab (`409`, `413`,
`507` …), liest sie seinen Inhalt bis `teil_max_bytes` trotzdem und verwirft
ihn – so kommt die Antwort beim Gerät an, statt in einem Verbindungsabbruch
unterzugehen. Größere oder nicht angemeldete Anfragen beantwortet sie und
schließt die Verbindung.

Kommt ein Stück nur teilweise an (Verbindung weg), verwirft die Software den
angefangenen Rest dieses Stücks. `naechstes_byte` zeigt danach wieder auf den
Anfang des Stücks.

### `GET /api/v1/aufnahmen/<Dateiname>/status`

Wie weit ist die Verarbeitung dieser Aufnahme? `<Dateiname>` ist der Name, den
das Gerät beim Hochladen benutzt hat (nicht der Name am PC). Das Gerät fragt
das ab, nachdem es die Aufnahme abgeschlossen hat, und zeigt den Stand an.

```json
{"zustand":"auswertung","fortschritt":0.8,"meldung":"…","aktualisiert":1760000000}
```

| `zustand` | Bedeutung | Gerät zeigt |
|---|---|---|
| `empfang` | Die Aufnahme läuft noch oder das Ende steht aus. `meldung` nennt, wie viele Blöcke die Software schon transkribiert hat. | – |
| `wartet` | Aufnahme komplett angekommen, die Verarbeitung ist eingereiht. | „Wird verarbeitet …" |
| `transkription` | Transkription läuft (nur noch der Rest, wenn schon während der Aufnahme transkribiert wurde). | Fortschritt |
| `transkript` | **Nur mit Rückfrage** (`X-Rueckfrage: 1`, siehe unten): Das Transkript steht, die Zusammenfassung wartet auf die Freigabe am Gerät. `meldung` ist `Transkription erfolgreich`. | **grünes Häkchen, „Transkription erfolgreich“**, dann die Frage „Zusammenfassung erstellen?“ |
| `auswertung` | Die Auswertung nach dem Auftrag läuft. | Fortschritt |
| `fertig` | Alles ist da. `meldung` ist `Transkription erfolgreich`. | **grünes Häkchen, „Transkription erfolgreich"** |
| `fehler` | Transkription oder Auswertung ist fehlgeschlagen oder wurde abgebrochen; `meldung` nennt, welcher Schritt. | Fehler |
| `unbekannt` | Der Software ist nichts bekannt (Neustart der Software, Live-Verarbeitung ausgeschaltet). Kein Fehler: Die Aufnahme liegt trotzdem vor. | nichts oder „angekommen" |

`fortschritt` (0 bis 1) fehlt, wenn die Software keinen kennt; er läuft über
Transkription **und** Auswertung (erste Hälfte Transkription, zweite Auswertung).
`aktualisiert` ist die Unix-Zeit der letzten Änderung. Das Gerät braucht keine
eigene Uhr dafür und fragt alle paar Sekunden ab (2 bis 5 s genügen). Die
Antwort ist immer `200`, solange das Token gilt (ein ungültiger Dateiname: `400`).

Regeln für das Gerät (die Firmware des S3 mit Bildschirm hält sich daran):

* Abfragen alle **3 s**, beginnend mit dem `"fertig":true` des Abschlusses,
  bis `fertig` oder `fehler` kommt.
* **Dreimal hintereinander `unbekannt`:** aufhören, nichts anzeigen (oder
  „angekommen").
* **`4xx`** (außer `408` und `429`) – etwa `404` von einer älteren Software
  ohne `…/status` oder `401`, weil das Token widerrufen ist: sofort aufhören,
  wie bei `unbekannt`. Wiederholen hilft hier nicht. Nur keine Antwort, `408`,
  `429` und `5xx` gelten als vorübergehend: in 3 s erneut fragen.
* Nach **3 Stunden** ohne `fertig` oder `fehler` aufhören.
* Beginnt eine neue Aufnahme, endet die Abfrage der vorigen.

Der Stand liegt nur im Speicher der Software. Nach einem Neustart der Software
meldet sie `unbekannt`; die Aufnahme selbst ist dann trotzdem sicher abgelegt.
Lädt ein Gerät eine schon abgelegte Aufnahme noch einmal hoch (die Bestätigung
ging verloren), bleibt der bisherige Stand stehen – ein `fertig` wird dadurch
nicht zurückgenommen.

### `GET /api/v1/auftraege`

Die Namen der Vorlagen (Systemprompts), aus denen das Gerät **vor der Aufnahme** einen Auftrag wählen lässt
(Auswahlliste am Display). Es sind höchstens 40 Namen mit je höchstens 60 Zeichen.

```json
{"auftraege":["Aufgaben und Zuständigkeiten","Entscheidungen","Meetingprotokoll"]}
```

Ältere Software kennt den Aufruf nicht (`404`): Das Gerät zeigt dann keine Auswahl.

### Auftrag und Rückfrage bei der Aufnahme

Zwei zusätzliche Kopfzeilen bei `PUT /api/v1/aufnahmen/<Dateiname>` (am besten bei jedem Stück, mindestens beim ersten):

| Kopfzeile | Bedeutung |
|---|---|
| `X-Auftrag` | Name der gewählten Vorlage, **UTF-8 prozentcodiert** (`Aufgaben%20f%C3%BCr%20Fritz`). Fehlt sie oder gibt es die Vorlage nicht (mehr), gilt der Auftrag aus den Einstellungen der Software. |
| `X-Rueckfrage` | `1`: Das Gerät will nach dem Transkript gefragt werden, ob die Zusammenfassung erstellt werden soll. Ohne die Kopfzeile läuft die Auswertung wie bisher von selbst weiter. |

Mit Rückfrage geht der Stand nach der Transkription auf `transkript` (siehe oben) und die Software wartet auf:

### `POST /api/v1/aufnahmen/<Dateiname>/zusammenfassung`

Das Gerät gibt die Zusammenfassung frei (Nutzer hat „Ja“ gewählt). Kein Inhalt nötig (höchstens 1 KB).

| Antwort | Bedeutung |
|---|---|
| `202 {"zustand":"auswertung"}` | Angenommen (auch bei einer Wiederholung, solange die Auswertung läuft). Ab jetzt wieder `/status` abfragen: `auswertung` → `fertig` (`meldung`: `Zusammenfassung fertig`). |
| `200 {"zustand":"fertig"}` | Die Zusammenfassung ist schon da. |
| `409 {"zustand":"…"}` | Das Transkript steht noch nicht (oder die Software nimmt es gerade nicht an): später noch einmal. |
| `404` | Der Software ist die Aufnahme nicht bekannt (Neustart) – oder sie kennt den Aufruf nicht. |

Vorab berechnete Teilergebnisse (siehe „Senden während der Aufnahme“) nutzt die Zusammenfassung wie bisher; nach der
Freigabe bleibt deshalb nur das Endergebnis zu rechnen.

### Fragen per Sprache

Nach dem Transkript kann das Gerät Fragen zu dieser Aufnahme stellen („Wer hat welche Aufgabe?“). Alles rechnet
lokal auf dem PC: Whisper versteht die Frage, das Sprachmodell antwortet aus Transkript und Zusammenfassung, eine
lokale Sprachausgabe spricht die Antwort. Die Frage läuft im Hintergrund; das Gerät fragt den Stand ab (wie bei `/status`).

**Ausgabe:** Standard ist **Text für das Display** (`X-Ausgabe: anzeige`): `anzeige` im Stand ist eine kurze nummerierte Liste, nur ASCII
(Umlaute als ae, oe, ue, ss, weil die Schriften der Geräte keine Umlaute haben), jeder Punkt höchstens zwölf Wörter, bis sechs Punkte;
fragt man nach einer bestimmten Anzahl („die vier wichtigsten Punkte“), hält die Antwort sie ein. Mit `X-Ausgabe: ton` wird die Antwort
zusätzlich gesprochen (siehe unten, sobald eine Sprachausgabe eingerichtet ist).

**`POST /api/v1/aufnahmen/<Dateiname>/frage`** – der Ton der Frage im Inhalt, `Content-Type: audio/wav` (16 kHz, 16 Bit,
mono) oder `audio/ogg` (Opus), höchstens 3 MB (etwa 90 s). Antworten:

| Antwort | Bedeutung |
|---|---|
| `202 {"frage_id":"…","ton":false}` | Angenommen. `ton` ist `true` nur, wenn das Gerät `X-Ausgabe: ton` verlangt hat **und** die Software eine Sprachausgabe hat. |
| `409` | Zu dieser Aufnahme gibt es noch kein Transkript (die Software kennt sie nicht oder sie ist noch in Arbeit). |
| `413` / `415` / `400` | Zu groß / kein `audio/wav` oder `audio/ogg` / kein Ton oder ungültiger Dateiname. |
| `404` | Die Software beantwortet keine Fragen per Sprache. |

**`GET /api/v1/fragen/<frage_id>`** – Stand der Frage:

```json
{"zustand":"antworten","frage":"Was macht Fritz?","meldung":"Antwort wird gesucht"}
```

| `zustand` | Bedeutung | Gerät zeigt |
|---|---|---|
| `verstehen` | Die Frage wird in Text umgewandelt. | „Ich höre …“ |
| `antworten` | Das Sprachmodell sucht die Antwort. `frage` ist schon da. | „Ich suche …“ |
| `sprechen` | Die Antwort wird gesprochen (`antwort` als Text ist schon da). | „Ich antworte …“ |
| `fertig` | `anzeige` (Text fürs Display) und `antwort` sind da; `ton_bytes` ist die Größe der WAV-Datei (0: kein Ton). | Liste anzeigen, ggf. Ton abspielen |
| `fehler` | `meldung` nennt den Grund (Frage nicht verstanden, Sprachmodell nicht erreichbar …). | Fehler |

**`GET /api/v1/fragen/<frage_id>/ton`** – die Antwort als WAV (`audio/wav`, 16 kHz, 16 Bit, mono) mit `Content-Length`;
nur bei `fertig` (sonst `409`, ohne Ton `404`). Die Kennung gehört dem Gerät, das gefragt hat: ein anderes Gerät bekommt
`404`. Fragen und Töne bleiben höchstens 15 Minuten im Speicher der Software.

Die Antwort ist kurz und gesprochen formuliert (höchstens vier Sätze, ohne Aufzählungen und Quellenangaben).

## Ablauf im Gerät

1. `GET /api/v1/hallo` an die konfigurierten Ziele (Server vor PC).
2. Für jede fertige Aufnahme: `GET /api/v1/aufnahmen/<Name>` → `N`.
3. Die ersten `N` Bytes der Datei lesen und in die SHA-256 einrechnen, dann
   ab `N` in Stücken `PUT` senden (die Firmware nimmt 256 KiB je Stück und
   streamt sie aus einem kleinen Puffer – das Stück muss nicht ins RAM passen).
4. Am Ende `PUT` mit `Content-Length: 0`, `X-Gesamtgroesse` und `X-SHA256`.
5. `"fertig":true` → lokale Kopie löschen.
6. `409` → ab dem gemeldeten Byte weiter (Prüfsumme ab Dateianfang neu
   berechnen). Meldet die Software mehr Bytes, als die Datei hat (die lokale
   Datei ist eine andere als der Teilstand), schickt das Gerät gleich den
   Abschluss mit seiner Größe – die Software antwortet `422` und verwirft den
   Teilstand. `422` → einmal von vorn; scheitert es erneut, diese Datei
   später noch einmal versuchen (bei jedem späteren Versuch wieder höchstens
   einmal von vorn).
7. Netzwerkfehler, `503`, `507`, drei Anfragen ohne Fortschritt hintereinander
   oder ein Abschluss mit `200`, aber ohne `"fertig":true`: **diese** Datei
   später erneut versuchen (5 s, dann jeweils doppelt so lange, höchstens
   5 min), mit der nächsten weitermachen – eine einzelne Datei hält die
   Warteschlange nicht auf.
8. `400`, `401`, `403`, `404`, `411`, `413`: Die Datei bleibt auf dem Gerät;
   neuer Versuch erst nach der längsten Wartezeit (5 min). Ein `401` beim
   `hallo` heißt: Token falsch – das Ziel gilt als nicht erreichbar.

## Ablage in der Software

* Fertige Aufnahmen landen als `<Gerät>_<Dateiname>` im Eingangsordner – in
  der Anwendung im eingestellten Eingabeordner (sonst `aufnahmen/`), im
  Servermodus in `PROTOKOLL_EINGANG`. Gibt es den Namen schon (mit anderem
  Inhalt), wird `_2`, `_3` … angehängt.
* Teilstände liegen bis zum Abschluss im versteckten Unterordner
  `.empfang/` desselben Ordners. Der Servermodus und die Dateiliste der
  Anwendung übergehen ihn. Teilstände, die sieben Tage nicht weitergewachsen
  sind, räumt der Dienst beim Start weg.
* Die Datei erscheint erst mit dem Abschluss im Eingangsordner – vollständig
  und auf einen Schlag (Umbenennen im selben Ordner). Halbe Aufnahmen sieht
  die Verarbeitung nie.

## Senden während der Aufnahme

Ein Gerät kann die Bytes seiner wachsenden Datei laufend anhängen (alle 15 s die
neuen, vollständig geschriebenen Ogg-Seiten) und erst am Ende abschließen. Die
Software nutzt die Zeit bis dahin (`services/live_service.py`):

* Aus der wachsenden **Ogg-Opus**-Datei transkribiert sie **laufend** mit einem
  gleitenden Fenster – mit Whisper auf dem Prozessor. Sind seit dem letzten
  sicheren Punkt mindestens 20 s neues Audio da, wird von diesem Punkt bis jetzt
  transkribiert (höchstens 45 s je Fenster). Was Whisper dabei sicher
  abgeschlossen hat, ist *bestätigt*; das letzte Segment am Fensterende kann
  abgeschnitten sein und wird im nächsten Fenster neu mitgerechnet. Das
  Transkript wächst so mit etwa 20 bis 40 s Verzögerung, ohne zerhackte Wörter.
  Die Dauer der Datei liest die Software aus der Granulposition der letzten
  vollständigen Ogg-Seite; eine mitten in einer Seite abgeschnittene Datei stört
  nicht. Dateien in anderen Formaten (`.wav`, `.mp3`) werden nicht live verarbeitet.
* Mit dem **Abschluss** (`fertig:true`) beginnt die Verarbeitung der fertigen
  Datei. Sie übernimmt die bestätigten Segmente und transkribiert nur den Rest ab
  dem sicheren Punkt (die letzten Sekunden), danach folgen Sprechertrennung und
  die Auswertung nach dem Auftrag aus den Einstellungen. Ein gerade laufendes
  Fenster wird noch fertig gerechnet, ein neues nicht mehr angefangen.
* Das Transkript wächst während der Aufnahme auch in der Vorschau der Anwendung
  (Seite „Ergebnis und Sprecher“), solange dort nichts anderes läuft.
* Auch die **Auswertung** wird vorbereitet (`services/live_auswertung_service.py`): Sobald der
  Text eines Auswertungsabschnitts (Standard 180 s, einstellbar 60–600 s) feststeht, wendet das Sprachmodell (auf der Grafikkarte, neben
  Whisper auf dem Prozessor) den Auftrag darauf an (Stufe 1); feststehende Gruppen von
  Teilergebnissen werden gleich zusammengeführt (Stufe 2). Nach dem Ende fehlen nur noch die
  letzten Abschnitte und das Endergebnis. Jedes Ergebnis gilt nur für genau seine Eingabe
  (Modell, Auftrag, Text): Die fertige Auswertung übernimmt es nur bei übereinstimmender Eingabe,
  sonst fragt sie neu. Damit die Texte übereinstimmen, bekommt das Modell dabei den Text
  **ohne Sprecherangaben** (die Sprechertrennung entsteht erst am Ende; im Transkript stehen die
  Sprecher trotzdem). Abschaltbar: *Aufnahmegeräte → Auswertung schon während der Aufnahme
  vorbereiten* (Standard: an). Ist das Sprachmodell nicht erreichbar, rechnet erst die
  Auswertung nach dem Ende, ohne Verlust.
* Das Gerät sieht den Stand über `…/status` (siehe oben).

Ob das geschieht, steht in den Einstellungen: *Aufnahmegeräte → Während der
Aufnahme transkribieren und nach dem Ende automatisch auswerten* (Standard: an).
Ist es aus, legt die Software die Aufnahme nur ab, und `…/status` meldet
`unbekannt`.

**Im Gerät** (umgesetzt am S3 mit Bildschirm,
`firmware/components/vermerk_upload/vermerk_live.c`; S3-AUDIO und C6 laden die
fertige Aufnahme wie bisher nach dem Ende hoch):

1. Vor dem ersten Stück `GET /api/v1/aufnahmen/<Name>`. Jeder Wert ungleich
   `0` heißt: Unter diesem Namen liegt schon ein Teilstand – für diese Datei
   **nicht** live senden. Sie wird nach dem Ende normal hochgeladen.
2. Alle **15 s** die neuen Bytes per `PUT` mit `X-Offset`, höchstens **64 KB**
   je Anfrage und **ohne** `X-Gesamtgroesse`/`X-SHA256`. Liegen 64 KB oder mehr
   unbestätigt vor, folgt das nächste Stück gleich – nach einem Fehlversuch
   aber erst wieder nach 15 s, damit eine überlastete Software nicht alle
   paar Sekunden angefragt wird.
3. `200` und `409` → ab `naechstes_byte` weiter; passt der Stand nicht zu dem,
   was das Gerät noch im Speicher hat (Lücke), endet das Live-Senden. Keine
   Antwort, `503`, `507` → beim nächsten Mal dieselben Bytes noch einmal.
   `400`, `401`, `403`, `404`, `411`, `413` … → Live-Senden für diese Aufnahme
   beenden.
4. Abgeschlossen wird erst nach dem Ende der Aufnahme, mit dem normalen Upload
   (Ablauf oben) ab dem Stand der Software. Endet das Live-Senden vorher (auch,
   weil der Zwischenspeicher im Gerät überläuft), geht nichts verloren: Die
   Aufnahme liegt ganz auf dem Gerät.
5. Danach den Verarbeitungsstand abfragen (Regeln unter `…/status`).

## Einrichtung über USB (Version 1)

Damit Kunden ein Gerät ohne Neukompilieren einrichten können, schreibt die
Software WLAN, Adresse und Token über das USB-Kabel ins Gerät. Das Gerät legt
sie im NVS (Flash) ab; sie haben Vorrang vor den einkompilierten Werten aus
`server_config.h`/`wifi_credentials.h`.

**Verbindung:** die serielle USB-Schnittstelle des Geräts (unter Windows ein
COM-Port; ESP32-S3/C6 mit eingebautem USB-Serial-JTAG, Hersteller-Kennung
`0x303A`). Die Software öffnet den Port mit **DTR und RTS aus** – sonst startet
der Chip neu oder in den Bootloader. Baudrate 115200 (für USB-Serial-JTAG
ohne Bedeutung).

**Zeilen:** ASCII, eine Anweisung je Zeile, Ende `\n`. Anweisungen an das
Gerät höchstens 512 Zeichen (längere: `#VERMERK FEHLER ZEILE zu lang …`),
Antworten des Geräts höchstens 1024 (eine `INFO` mit langem WLAN-Namen und
zwei Adressen kommt auf gut 700). Anweisungen der Software und Antworten des
Geräts beginnen mit `#VERMERK `; alles andere sind Protokollzeilen des Geräts
und werden übergangen. Werte werden **hexadezimal** übertragen (Bytes, zwei
Zeichen je Byte; die Software schickt klein, das Gerät nimmt beides) – so
stören Leerzeichen, Anführungszeichen oder Umlaute im WLAN-Namen nicht. Eine
unbekannte Anweisung beantwortet das Gerät mit
`#VERMERK FEHLER <Wort> unbekannte Anweisung`.

| Software → Gerät | Antwort | Bedeutung |
|---|---|---|
| `#VERMERK INFO` | `#VERMERK INFO {"geraete_id":"1a2b3c4d5e6f","board":"esp32-s3-audio","firmware":"1.0.0","eingerichtet":true,"wlan_hex":"…","pc_url_hex":"…","server_url_hex":"…","token_pc":true,"token_server":false}` | Wer ist da, was gilt gerade? Die Werte sind die **wirksamen** – ohne Einrichtung die einkompilierten; `eingerichtet` sagt, woher sie kommen. Passwort und Token werden **nie** ausgegeben, nur ob sie gesetzt sind. Kompaktes JSON wie bei HTTP. |
| `#VERMERK SETZE <Schlüssel> <Hex>` | `#VERMERK OK SETZE <Schlüssel>` oder `#VERMERK FEHLER <Schlüssel> <Text>` | Wert vormerken (noch nicht gespeichert). |
| `#VERMERK SPEICHERN` | `#VERMERK OK SPEICHERN` oder `#VERMERK FEHLER SPEICHERN <Text>` | Vorgemerkte Werte prüfen und **zusammen** speichern, danach Neustart (ca. 1 s). Läuft eine Aufnahme: Fehler, nichts gespeichert. |
| `#VERMERK VERWERFEN` | `#VERMERK OK VERWERFEN` | Vorgemerktes vergessen. |
| `#VERMERK LOESCHEN` | `#VERMERK OK LOESCHEN` oder `#VERMERK FEHLER LOESCHEN <Text>` | Eingerichtete Werte löschen (zurück zu den einkompilierten), danach Neustart. Während einer Aufnahme abgelehnt. Der Aufnahmezähler bleibt. |

Schlüssel und Grenzen:

| Schlüssel | Inhalt |
|---|---|
| `wlan_ssid` | 1–32 Bytes, Pflicht |
| `wlan_passwort` | leer (offenes WLAN) oder 8–63 druckbare ASCII-Zeichen (0x20–0x7E, wie WPA es verlangt) |
| `pc_url`, `server_url` | `http://<Rechner>[:Port]`, nur ASCII, höchstens 96 Bytes, ohne `/` am Ende (kein `https://` – die Firmware kann kein TLS); leer = Ziel nicht genutzt |
| `pc_token`, `server_token` | wie bei HTTP (1–128 sichtbare ASCII-Zeichen); Pflicht, wenn die zugehörige Adresse gesetzt ist |
| `erste_nummer` | Dezimalzahl als Text, z. B. `29`; optional – fehlt sie, gilt der einkompilierte Wert |

Beim `SPEICHERN` muss mindestens ein Ziel vollständig sein (Adresse **und**
Token). Was nicht gesetzt wurde, wird leer gespeichert (Ausnahme
`erste_nummer`, siehe oben) – eine Einrichtung ersetzt immer die ganze
vorherige. Kein Wert darf ein NUL-Byte enthalten.

**Ablauf in der Software:** Port öffnen → `INFO` (bis zu dreimal, das Gerät kann
gerade starten) → Gerätename vergeben, Token erzeugen → alle `SETZE` →
`SPEICHERN` → nach dem Neustart erneut `INFO` (zeigt `eingerichtet`). Läuft der
Empfang, meldet sich das Gerät danach mit seiner `X-Geraete-Id` – die Software
zeigt das als Bestätigung an. Die Geräte-Id, das Board und die Firmware merkt
sie sich beim Gerät (Grundlage für das Inventar).

Wer das Gerät per USB in der Hand hat, kann es neu einrichten – das ist
gewollt (physischer Zugriff). Auslesen lassen sich Passwort und Token nicht.
