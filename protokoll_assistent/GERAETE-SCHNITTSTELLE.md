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

## Später: Senden während der Aufnahme

Die Schnittstelle ist dafür schon ausgelegt: Ein Gerät kann die Bytes seiner
wachsenden Datei laufend anhängen (alle 15 s die neuen, vollständig
geschriebenen Ogg-Seiten) und erst am Ende abschließen. In der Software ist
dafür nichts weiter nötig. Was in der Firmware noch fehlt, steht in
`firmware/docs/streaming-konzept.md`.

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
