# VERMERK-Recorder: Firmware für die ESP32-Aufnahmegeräte

Diese Firmware nimmt Besprechungen auf, speichert sie auf dem Gerät und lädt sie per WLAN an den PC
oder Server hoch, auf dem die Protokoll-Software (`protokoll_assistent/`) die Aufnahmen transkribiert.
Sie gehört **nicht** zur Windows-Anwendung und wird nicht mit ihr ausgeliefert. Die CI baut alle drei Boards, testet den
reinen C-Teil der Upload-Komponente auf dem PC und den Upload in QEMU gegen den echten Empfang
(`.github/workflows/firmware.yml`, kein Pflicht-Check); ob die Firmware auf den Geräten läuft, prüft nur ein Test auf
echter Hardware.

| Ordner | Board | Chip | Bedienung | Aufnahme | Speicher |
|---|---|---|---|---|---|
| [`esp32-s3/lcd/`](esp32-s3/lcd/) | Waveshare ESP32-S3-Touch-LCD-1.85C | ESP32-S3, 2 Kerne, PSRAM | Touchscreen | Ogg-Opus, 16 kHz, Mono, 24 kbit/s | SD-Karte |
| [`esp32-s3/audio/`](esp32-s3/audio/) | Waveshare ESP32-S3-AUDIO-Board (ohne Bildschirm) | ESP32-S3, 2 Kerne, PSRAM | Tasten KEY1–3, BOOT; LED-Ring | Ogg-Opus, 16 kHz, Mono, 24 kbit/s | SD-Karte, sonst Flash |
| [`esp32-c6/`](esp32-c6/) | Waveshare ESP32-C6-Touch-LCD-1.83 | ESP32-C6, 1 Kern, kein PSRAM | Touchscreen | Ogg-Opus, 16 kHz, Mono, 24 kbit/s (umschaltbar auf MP3) | SD-Karte, sonst Flash (ca. 13,8 MB) |

Ausführliche Bedienung, LED- und Tastenbelegung der beiden S3: [`esp32-s3/README.md`](esp32-s3/README.md).

Alle Versionen haben dieselbe Aufnahme-, Pause- und Upload-Logik; Treiber, Pinbelegung und Bedienung unterscheiden sich je nach Board. Der C6 zeigt außerdem den
USB-/Ladezustand direkt vom Power-Chip AXP2101 an, statt ihn aus der Akkuspannung zu erraten.

## Geplant: Live-Übertragung

Die Geräte sollen im WLAN der Software die Aufnahme in 15-s-Stücken schon während der Aufnahme an den PC schicken, wo sie
laufend transkribiert und mit einem vorgegebenen Auftrag ausgewertet wird; das Gerät zeigt am Ende „Transkription erfolgreich“.
Das Konzept mit Entscheidungen und Phasen steht in [`docs/streaming-konzept.md`](docs/streaming-konzept.md). Die Übertragung
selbst ist umgesetzt (wiederaufnehmbarer Upload mit Token, siehe [Gegenstelle](#gegenstelle-die-protokoll-software)); das
Senden schon **während** der Aufnahme fehlt in der Firmware noch.

## Lautstärke

Alle Geräte regeln den Aufnahmepegel automatisch (AGC, `main/Gain_Control/`): leise Sprache wird bis +18 dB angehoben,
laute Stellen werden begrenzt, Rauschen in Pausen wird nicht hochgezogen. Ohne das lag eine Aufnahme aus einigen
Metern Abstand bei ca. −55 dB im Mittel und war beim Abspielen kaum zu hören.

## Warum Mono, 16 kHz?

Die Protokoll-Software wandelt jede Eingabe vor der Transkription per ffmpeg in Mono, 16 kHz, 16 Bit um
(`services/ffmpeg_service.py`). Stereo und höhere Abtastraten kosten auf dem Gerät nur Speicherplatz.

## Speicher: SD-Karte oder Flash (C6 und S3-AUDIO-Board)

Beim Einschalten wird zuerst eine SD-Karte (FAT32) gesucht. Steckt eine, wird dort aufgenommen. Sonst liegen die
Aufnahmen in einer FAT-Partition im Flash (ca. 13,8 MB). Eine fremde Karte wird nie formatiert; die Karte nur im
ausgeschalteten Zustand wechseln. Der Upload sucht in beiden Speichern. Nach dem Hochladen löscht das Gerät die
Datei wieder. Die Zahlen unten gelten für die Aufnahme im Flash. Die Bitrate steht in `esp32-c6/main/Opus_Encoder/Opus_Encoder.h`
(`OPUS_BITRATE_BPS`), das Format in `esp32-c6/main/Rec_Codec.h` (`REC_CODEC_OPUS 1` = Opus, `0` = MP3):

| Bitrate | pro Stunde | Aufnahmezeit im Flash (13,8 MB) |
|---|---|---|
| 16 kbit/s | 7,2 MB | ca. 115 min |
| 24 kbit/s (Standard) | 10,8 MB | ca. 77 min |
| 32 kbit/s | 14,4 MB | ca. 58 min |

Messung mit dem Whisper der Protokoll-Software (large-v3-turbo) an vier echten Aufnahmen: Bei sauberer Sprache ist
selbst 12 kbit/s unauffällig; bei schlechtem Material (Rauschen, Abstand zum Mikrofon) wächst die Abweichung
vom Transkript des unkomprimierten Originals unterhalb von 24 kbit/s spürbar. Die Stichprobe ist klein, die
Streuung von Whisper selbst liegt bei einigen Prozent.

Der C6 hat keinen PSRAM (die S3 haben 8 MB, das RAM ist dort weniger knapp, aber auch nicht üppig). Damit Aufnahme, Encoder und Upload gleichzeitig laufen, ist der RAM bewusst knapp
bemessen (Encoder ca. 25 KB, Encoder-Stack 28 KB, kleine Display- und Upload-Puffer, nur ein I2S-Aufnahmekanal).
Der Encoder muss früh in `app_main` angelegt werden, solange noch ein großer zusammenhängender Block frei ist.

## Bauen und flashen

ESP-IDF v5.5.x, jeweils im Ordner des Boards. Die S3 sind in [`esp32-s3/README.md`](esp32-s3/README.md) ausführlicher beschrieben.

```
idf.py set-target esp32s3     # bzw. esp32c6
idf.py -p COMx build flash
```

Vorher die beiden Vorlagen kopieren und ausfüllen (die echten Dateien sind in `.gitignore` und kommen nie ins Repository):

* `main/Wireless/wifi_credentials.h.example` → `wifi_credentials.h` (WLAN-Name und Passwort)
* `main/Wireless/server_config.h.example` → `server_config.h` (Adresse und Token der Protokoll-Software, siehe unten)

Fehlt eine der beiden Dateien, bricht der Build mit einem Hinweis ab. Eine `server_config.h` aus der Zeit vor der neuen
Schnittstelle (ohne `VERMERK_PC_TOKEN`) wird ebenfalls abgelehnt: dann die Vorlage neu kopieren.

## Gegenstelle: die Protokoll-Software

Die Geräte laden direkt in die Protokoll-Software hoch, in die Windows-Anwendung oder in den Servermodus. Ablauf, Kopfzeilen
und Antworten stehen verbindlich in [`protokoll_assistent/GERAETE-SCHNITTSTELLE.md`](../protokoll_assistent/GERAETE-SCHNITTSTELLE.md).

**Einrichten:**

1. Empfang einschalten: in der Anwendung unter Einstellungen, Bereich „Aufnahmegeräte“; im Servermodus mit
   `PROTOKOLL_EMPFANG=1`. Standardport 8765.
2. Für **jedes Gerät ein eigenes Token** erzeugen: in der Anwendung im selben Bereich, im Servermodus mit
   `python -m protokoll_assistent.server --token-erzeugen <Name>`. Der Name wird Teil des Dateinamens
   (`<Name>_H5_007.opus`). Das Token wird nur einmal angezeigt; die Software speichert nur seinen Hash.
3. In `main/Wireless/server_config.h` Adresse und Token eintragen: `VERMERK_PC_BASE_URL` und `VERMERK_PC_TOKEN`
   und/oder `VERMERK_SERVER_BASE_URL` und `VERMERK_SERVER_TOKEN`. Bauen, flashen.
4. Im Monitor erscheint `VERMERK PC erreichbar (Stuecke bis 256 KB)` (bzw. `SERVER`). `lehnt das Token ab (HTTP 401)`
   heißt: Token falsch oder in der Software widerrufen.

**So läuft der Upload** (Code: [`components/vermerk_upload/`](components/vermerk_upload/), für alle drei Boards gleich):

* Ein Ziel gilt nur als erreichbar, wenn `GET /api/v1/hallo` mit gültigem Token antwortet und sich als Protokoll-Software
  ausweist; ein beliebiger Webserver, der `200` liefert, genügt nicht. Sind beide erreichbar, hat der Server Vorrang.
* Hochgeladen wird in Stücken von 256 KiB mit Byte-Versatz, gestreamt aus einem kleinen Puffer (C6: 4 KB, S3: 16 KB,
  bei knappem RAM 4 KB). Reißt die Verbindung ab, macht das Gerät beim letzten bestätigten Byte weiter, auch nach einem
  Neustart. Zum Schluss prüft die Software Größe und SHA-256. **Erst wenn sie „fertig“ meldet, löscht das Gerät seine Kopie.**
* Scheitert eine Datei, wartet nur diese (5 s, dann jeweils doppelt so lang, höchstens 5 min); die nächste ist trotzdem
  dran. Die Wartezeiten liegen nur im RAM, nach einem Neustart geht es sofort los.
* Startet eine Aufnahme, hört der Upload nach dem laufenden Stück auf und macht später an derselben Stelle weiter.
* Jede Anfrage trägt außerdem `X-Geraete-Id` (Werks-MAC aus dem eFuse) und `X-Firmware` (z. B. `esp32-c6/1.0.0`), nur zur
  Zuordnung und Fehlersuche. Beim Start steht beides im Monitor: `VERMERK Geraete-Id: 1a2b3c4d5e6f, Firmware: …`.
  Welches Gerät (Id) mit welcher Firmware wo im Einsatz ist, steht im **privaten** Repository
  [`Blickfeld-KevinLemaire/aufnahmegeraete-inventar`](https://github.com/Blickfeld-KevinLemaire/aufnahmegeraete-inventar)
  (nur für Berechtigte) – Kundendaten gehören nicht in dieses öffentliche Repository. Jedes neue Gerät dort eintragen.
* Jedes Gerät zählt seine Dateien selbst (H5_001, H5_002 …), mehrere Geräte erreichen also dieselben Nummern. Die Software
  legt jede Aufnahme als `<Gerätename>_<Dateiname>` im Eingangsordner ab (Gerätename aus dem Token) und hängt bei gleichem
  Namen mit anderem Inhalt `_2`, `_3` … an; überschrieben wird nie. Von dort läuft die Aufnahme durch die normale Verarbeitung.
* Übertragen wird per HTTP im eigenen Netz. Das Token schützt davor, dass Fremde Dateien einliefern oder die Software
  vortäuschen; mitlesen kann im selben WLAN trotzdem, wer den Datenverkehr abgreift (siehe `SECURITY.md`).
* Alle Verbindungs-Einstellungen (WLAN, Adressen, Tokens, erste Nummer) liest die Firmware nur über
  `components/vermerk_upload/include/vermerk_konfig.h`. Heute stehen sie fest im Build; sollen Kunden sie später selbst
  setzen (z. B. per USB aus der Anwendung), ändert sich nur `vermerk_konfig.c`.

**Nummern:**

* `VERMERK_UPLOAD_ERSTE_NUMMER` (optional in `server_config.h`): Aufnahmen mit kleinerer Nummer werden nicht hochgeladen,
  Standard 1 (alle). **Das vorhandene S3 mit Bildschirm** hatte bisher fest 29 im Code: dort
  `#define VERMERK_UPLOAD_ERSTE_NUMMER 29` in die eigene `server_config.h` eintragen, sonst lädt es H5_001 bis H5_028
  hoch, falls die noch auf der Karte liegen.
* Ab Nummer 1000 heißen die Dateien `H5_1000.opus` usw. Zählen, Upload und die Suche nach der höchsten Nummer beim Start
  lesen jetzt die Verzeichnisliste statt jede Nummer von 1 bis 999 einzeln zu öffnen; die alte Grenze 999 gibt es nicht
  mehr (Obergrenze jetzt 999 999 999). Ein Upload-Durchgang nimmt die 32 kleinsten offenen Nummern, der nächste den Rest.

**Teststand der neuen Übertragung (12.10.2026): in QEMU gegen die echte Software getestet, noch nicht auf einem Gerät.**

* **Build:** Alle drei Firmwares bauen mit ESP-IDF v5.5.5.
* **Tests auf dem PC** (`components/vermerk_upload/test/host/`, `make test`, gcc mit AddressSanitizer und
  UndefinedBehaviorSanitizer): der reine C-Teil (Antworten lesen, Dateinamen, Wartezeiten, Entscheidung nach jeder Antwort,
  Geräte-Id). Dazu ein **Vertrag mit der Software**: `antworten_software.h` enthält echte Antworten des Empfangs (erzeugt
  von `antworten_erzeugen.py`), die die Firmware genau so lesen muss. Die CI erzeugt sie neu und bricht ab, wenn sich das
  Format ändert.
* **Ende-zu-Ende in QEMU** (`components/vermerk_upload/test/qemu/run_e2e.sh`): Der echte Upload-Code (esp_http_client,
  mbedtls, `vermerk_upload`) läuft auf einem emulierten ESP32 mit Ethernet gegen den echten Empfang
  (`services/geraete_empfang_service.py`), alles in einem Container. Geprüft: Hallo mit Token; Upload in drei Stücken;
  Wiederaufnahme bei einem Teilstand der Software; falsches Token (401, Datei bleibt); dieselbe Aufnahme zweimal (eine
  Datei, beide Male „fertig“); Verbindung mitten im Stück gekappt, danach Fortsetzung; Abbruch zwischen zwei Stücken
  (neue Aufnahme), danach Fortsetzung; `409` auf ein volles Stück, Fortsetzung beim gemeldeten Byte; `422` (falscher
  Teilstand und Teilstand größer als die Datei), einmal von vorn; `X-Geraete-Id` und `X-Firmware` kommen an. Jede Datei
  liegt danach Byte für Byte gleich im Eingangsordner.

**Nicht geprüft** (nur auf echter Hardware zu klären): WLAN statt Ethernet, die Chips S3 und C6 (QEMU emuliert den
klassischen ESP32; die Komponente ist chipunabhängig), Durchsatz und Dauer auf den Geräten, Upload von SD-Karte,
Wiederaufnahme nach einem echten Neustart des Geräts (in QEMU nur über einen neuen Aufruf), der Upload-Manager in
`main.c` (Warteliste, `.sent`-Marker, Löschen nach „fertig“), RAM und Stack auf dem C6 während Aufnahme und Upload (die
Zeile `VERMERK Upload-Diagnose` zeigt dafür `Puffer` und `Stack frei`; in QEMU blieben von 8 KB Stack ca. 5,5 KB frei),
die Werks-MAC aus dem eFuse (QEMU liefert `000000000000`). Die Upload-Messungen in `esp32-s3/README.md` stammen noch vom
früheren Upload (`POST /upload`).

## Fremder Code

* `esp32-c6/components/shine/`: MP3-Encoder [shine](https://github.com/toots/shine), **LGPL-2.0** (siehe `COPYING`),
  mit den in der dortigen `README.md` beschriebenen Änderungen. Wird die Firmware weitergegeben, gelten die
  LGPL-Pflichten (Quelltext des Encoders und Änderungen bereitstellen).
* Opus-Encoder: Komponente `espressif/esp_audio_codec` (wird beim Bauen geladen, nicht im Repository). Ihre Lizenz
  (Espressif Modified MIT) erlaubt die Nutzung nur auf Espressif-Chips; das trifft hier zu.
* `esp32-s3/audio/`: IO-Expander-Treiber `espressif/esp_io_expander_tca95xx_16bit` und LED-Treiber `espressif/led_strip`
  (werden beim Bauen geladen); Pinbelegung und Ablauf nach dem Waveshare-Beispiel für das ESP32-S3-AUDIO-Board.
* `esp32-c6/components/XPowersLib/`: [XPowersLib](https://github.com/lewisxhe/XPowersLib) (MIT), Treiber für den AXP2101.
* Teile der Treiber stammen aus den Beispielprojekten von Waveshare für die jeweiligen Boards
  ([ESP32-C6-Touch-LCD-1.83](https://github.com/waveshareteam/ESP32-C6-Touch-LCD-1.83)).
* LVGL, `esp_codec_dev`, `esp_lcd_touch` u. a. werden beim Bauen über den ESP-IDF-Komponentenmanager geladen
  und sind nicht im Repository.
