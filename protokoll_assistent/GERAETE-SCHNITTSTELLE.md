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
  unbekannt: `401`.
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
* Dateinamen: Buchstaben, Ziffern, `_` und `-`, höchstens 64 Zeichen, dann
  eine Endung aus `.opus`, `.ogg`, `.wav`, `.mp3` (z. B. `H5_007.opus`).
  Anderes: `400`.

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

Kommt ein Stück nur teilweise an (Verbindung weg), verwirft die Software den
angefangenen Rest dieses Stücks. `naechstes_byte` zeigt danach wieder auf den
Anfang des Stücks.

## Ablauf im Gerät

1. `GET /api/v1/hallo` an die konfigurierten Ziele (Server vor PC).
2. Für jede fertige Aufnahme: `GET /api/v1/aufnahmen/<Name>` → `N`.
3. Die ersten `N` Bytes der Datei lesen und in die SHA-256 einrechnen, dann
   ab `N` in Stücken `PUT` senden (die Firmware nimmt 256 KiB je Stück und
   streamt sie aus einem kleinen Puffer – das Stück muss nicht ins RAM passen).
4. Am Ende `PUT` mit `Content-Length: 0`, `X-Gesamtgroesse` und `X-SHA256`.
5. `"fertig":true` → lokale Kopie löschen.
6. `409` → ab dem gemeldeten Byte weiter (Prüfsumme ab Dateianfang neu
   berechnen). `422` → einmal von vorn; scheitert es erneut, diese Datei
   später noch einmal versuchen.
7. Netzwerkfehler, `503`, `507`: **diese** Datei später erneut versuchen
   (wachsende Wartezeit), mit der nächsten weitermachen – eine einzelne
   Datei hält die Warteschlange nicht auf.

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

## Später: Senden während der Aufnahme

Die Schnittstelle ist dafür schon ausgelegt: Ein Gerät kann die Bytes seiner
wachsenden Datei laufend anhängen (alle 15 s die neuen, vollständig
geschriebenen Ogg-Seiten) und erst am Ende abschließen. In der Software ist
dafür nichts weiter nötig. Was in der Firmware noch fehlt, steht in
`firmware/docs/streaming-konzept.md`.
