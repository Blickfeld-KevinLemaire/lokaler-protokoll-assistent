# VERMERK-Recorder auf dem ESP32-S3

Zwei Boards, dieselbe Aufnahme-Software: Das Gerät nimmt Besprechungen auf, speichert sie als kleine
Opus-Dateien und schickt sie per WLAN an den PC oder Server, auf dem die Protokoll-Software sie transkribiert.

| | **S3 mit Bildschirm** | **S3 ohne Bildschirm** |
|---|---|---|
| Board | Waveshare ESP32-S3-Touch-LCD-1.85C | Waveshare ESP32-S3-AUDIO-Board |
| Ordner | [`lcd/`](lcd/) | [`audio/`](audio/) |
| Bedienung | Touchscreen (Start, Pause, Stopp) | 3 Tasten **KEY1–KEY3** und **BOOT** (RESET startet nur neu) |
| Anzeige | Bildschirm: Zustand, Zeit, Pegel, Verbindung, Akku | 7 RGB-LEDs im Ring |
| Speicher | SD-Karte | SD-Karte; ohne Karte automatisch der Flash (ca. 13,8 MB = ca. 77 min) |
| Stand | auf Hardware getestet | Aufnahme, Speicher und Upload auf dem echten Board getestet; **Tasten und LED-Ring noch nicht von Hand bestätigt** (siehe unten) |

## Gemeinsam

* **Aufnahmeformat:** Ogg-Opus (`.opus`), Mono, 16 kHz, 24 kbit/s (variable Bitrate). Die beiden Mikrofone werden
  zu Mono gemischt. Das passt zur Protokoll-Software, die alles ohnehin auf Mono/16 kHz umrechnet
  (`services/ffmpeg_service.py`).
* **Lautstärke (AGC):** Leise Sprache (Abstand, Raum) wird beim Aufnehmen automatisch auf eine einheitliche Höhe
  gebracht: bis zu +18 dB Anhebung, laute Stellen werden begrenzt (nie übersteuert), Stille und Rauschen werden nicht
  hochgezogen. Gemessen am AUDIO-Board mit derselben Quelle: Mittelwert −55 dB → −37 dB, Spitzen −22 → −2,6 dBFS, kein
  übersteuertes Sample. Der Code liegt in `main/Gain_Control/`. Ältere Aufnahmen bleiben natürlich leise.
* **Dateigröße:** ca. 3 KB pro Sekunde, 10,8 MB pro Stunde. Auf eine 32-GB-Karte passen weit über 1000 Stunden.
  Früher (WAV, Stereo) waren es 115 MB pro Stunde.
* **Dateinamen:** `H5_001.opus`, `H5_002.opus` … fortlaufend. Der Zähler überlebt Neustarts und wird nie zurückgesetzt.
* **Upload:** Sobald das Gerät im WLAN ist und der Empfänger antwortet, werden Aufnahmen hochgeladen, **aber nie
  während einer laufenden Aufnahme**. Nach erfolgreichem Upload löscht das Gerät seine Kopie. Fällt die
  Verbindung aus, bleibt die Aufnahme auf dem Gerät und wird später nachgeholt.
* **Alte Aufnahmen:** `.wav`-Dateien von der früheren Firmware (S3 mit Bildschirm) werden weiter hochgeladen.
* **Voller Speicher:** Unter 64 KB frei beendet das Gerät die Aufnahme sauber und speichert sie. Unter 256 KB frei
  startet keine neue Aufnahme.
* **Stromausfall:** Alle 30 Sekunden wird die Datei gesichert. Es gehen höchstens die letzten Sekunden verloren;
  die Datei bleibt abspielbar.

### Empfänger (Gegenstelle)

Das Gerät sendet `POST /upload` (Dateiname im Header `X-Filename`) und fragt `GET /vermerk-status.txt` ab,
um zu prüfen, ob die Gegenstelle da ist. Ein fertiger Mini-Empfänger liegt als
[`../tools/vermerk_receiver.py.txt`](../tools/vermerk_receiver.py.txt) (zu `.py` umbenennen und mit `python`
starten; er liegt als `.txt`, damit die Python-Prüfungen des Repositorys nicht anschlagen). Er speichert nach
`uploads/`, Port 8765. Die Ordnerüberwachung der Protokoll-Software nimmt `.opus` direkt an.

### Einrichten (einmalig, beide Boards)

1. ESP-IDF 5.5.x installieren, Eingabeaufforderung/PowerShell mit der ESP-IDF-Umgebung öffnen.
2. Im Ordner des Boards (`lcd/` oder `audio/`) unter `main/Wireless/` die beiden Vorlagen kopieren und ausfüllen:
   `wifi_credentials.h.example` → `wifi_credentials.h` (WLAN-Name, Passwort) und
   `server_config.h.example` → `server_config.h` (Adresse des Empfängers, z. B. `http://192.168.0.10:8765`).
   Diese beiden Dateien stehen in der `.gitignore` und gehören nie ins Repository.
3. `idf.py set-target esp32s3`
4. `idf.py -p COMx build flash` (COM-Port im Geräte-Manager nachsehen; der Chip meldet sich als „USB JTAG/serial debug unit“).
5. Mitlesen: `idf.py -p COMx monitor` (beenden mit Strg+AltGr+`]`).

Die Aufnahme-Bitrate ändert man in `…/main/Opus_Encoder/Opus_Encoder.h` (`OPUS_BITRATE_BPS`:
16000 / 24000 / 32000). Unterhalb von 24 kbit/s wird die Erkennung bei schlechtem Material (Rauschen, großer
Abstand zum Mikrofon) spürbar schlechter, bei sauberer Sprache nicht.

---

## S3 mit Bildschirm (Touch-LCD-1.85C)

Bedienung ausschließlich über den Touchscreen. Die zwei Tasten am Gehäuse haben in dieser Firmware keine Funktion.

* **AUFNAHME STARTEN** → Zeit läuft, roter Punkt blinkt, die Wellenform zeigt den Pegel.
* **PAUSE** (rechts neben STOPP) hält die Aufnahme an; die Wellenform friert ein.
* **STOPP** beendet und speichert. Danach steht kurz „GESPEICHERT“ im Display.
* Oben: **LOKAL / WLAN / PC / SERVER** zeigt, ob und wohin hochgeladen werden kann (Pfeil = Upload läuft).
  **AKKU xx %** mit Blitz, wenn geladen wird. Unten: „n AUFNAHMEN OFFEN“, wenn noch etwas hochzuladen ist.
* „MIKROFON PRUEFEN“ erscheint nur, wenn ein Mikrofon nichts mehr liefert.

---

## S3 ohne Bildschirm (AUDIO-Board)

> **Stand (11.10.2026):** Auf dem echten Board geprüft: Start, Mikrofon (beide werden zu Mono gemischt), Opus-Aufnahme
> (Last ca. 25 % eines Kerns, ca. 99 KB RAM frei), Aufnahme in den Flash, Upload an den Empfänger (ca. 100 KB in 120 ms),
> sauberes Speichern und das Erkennen von IO-Expander und LED-Ring. Eine Testaufnahme mit gesprochenem Text wurde von
> Whisper fehlerfrei transkribiert. **Noch nicht von Hand bestätigt:** die Reaktion der Tasten KEY1–KEY3/BOOT, die
> Farben des LED-Rings und die SD-Karte (im Test steckte keine). Im Monitor erscheint bei jeder Tastenänderung eine Zeile
> `KEYS: Expander-Eingaenge: …` und bei jedem erkannten Druck `VERMERK Taste KEY1 kurz` bzw. `lang`; damit lässt sich die
> Belegung am eigenen Gerät sofort prüfen.

### Bedienung

| Taste | Kurz drücken | **1 Sekunde halten** |
|---|---|---|
| **KEY1** (oder **BOOT**) | Aufnahme **starten** | Aufnahme **beenden und speichern** |
| **KEY2** | **Pause** / **Weiter** | – |
| **KEY3** | Speicher-Füllstand anzeigen (3 s) | – |
| **RESET** | Neustart | – |

Beenden geht bewusst nur durch Halten: Ein versehentlicher kurzer Druck mitten in der Besprechung
beendet nichts, sondern lässt den Ring kurz orange aufblitzen. Beim Halten füllt sich der Ring weiß; ist er voll,
wird gespeichert.

### LED-Ring

| Anzeige | Bedeutung |
|---|---|
| Weißer Punkt kreist | Gerät startet |
| Ring atmet ruhig **blau** | bereit, kein WLAN (Aufnahmen bleiben auf dem Gerät) |
| Ring atmet **türkis** | bereit, im WLAN, aber der Empfänger antwortet nicht |
| Ring atmet **grün** | bereit, Empfänger erreichbar |
| Orange Punkt oben im Ring | es liegen noch Aufnahmen auf dem Gerät, die hochgeladen werden müssen |
| Grüner Punkt wandert | Upload läuft |
| **Rot**, mit dem Pegel mitwachsend | **Aufnahme läuft.** Mindestens eine LED bleibt immer rot. |
| Orange blinkt langsam | Pause |
| Ring weiß | wird gestartet / gespeichert |
| Ring grün (2,5 s) | gespeichert |
| Orange/rot im Wechsel (2,5 s) | Speicher voll, Aufnahme wurde gespeichert und beendet |
| Rot, schnell blinkend (5 s) | Aufnahme nicht möglich (kein Speicher, zu wenig Platz, Schreibfehler) |
| Violett blinkt | Mikrofon liefert keine Daten |
| KEY3: Balken | Füllstand: wenige LEDs = leer, Farbe grün → orange (ab 70 %) → rot (ab 90 %); die nächste LED zeigt den Speicher: **blau = SD-Karte, türkis = Flash** |

Die rote LED während der Aufnahme lässt sich nicht abschalten. Wer aufgenommen wird, soll es sehen können.

### Speicher

Beim Einschalten wird zuerst eine **SD-Karte (FAT32)** gesucht. Steckt eine, geht die Aufnahme dorthin.
Steckt keine (oder eine nicht lesbare), wird im **Flash** aufgenommen (ca. 13,8 MB, ca. 77 Minuten). Eine fremde
Karte wird nie formatiert. **Karte nur im ausgeschalteten Zustand wechseln** und danach neu starten (RESET);
im Betrieb wird sie nicht erkannt. Aufnahmen, die im jeweils anderen Speicher liegen, werden trotzdem hochgeladen.

### Erster Einsatz: Checkliste

1. Mit **Datenkabel** (nicht nur Ladekabel) an den PC, Port im Geräte-Manager nachsehen, flashen (siehe oben).
2. Monitor öffnen. Es sollten diese Zeilen erscheinen:
   `LEDS: LED-Ring bereit`, `OPUS: Encoder bereit`, `KEYS: Tasten bereit`,
   `STORAGE: SD-Karte erkannt …` (oder `Keine SD-Karte … nutze Flash`), `VERMERK bereit: KEY1/BOOT = Start …`.
3. Ring atmet ruhig (blau/türkis/grün) → Verbindungsstatus passt zur Umgebung?
4. **KEY1** kurz: Ring wird rot, Pegel wächst beim Sprechen. Im Monitor läuft alle 10 s eine Zeile
   `VERMERK REC: Encoder-Last … %, Speicher frei …`.
5. **KEY2**: Ring blinkt orange, nochmal **KEY2**: weiter.
6. **KEY1 halten**: Ring füllt sich weiß, dann grün. Nach kurzer Zeit „Upload + Loeschen erfolgreich“ im Monitor und die
   Datei im Empfängerordner.
7. **KEY3**: Balken mit Füllstand.

### Wenn etwas nicht geht

* **Der PC erkennt das Board nicht** (kein neuer COM-Port): anderes USB-C-Kabel mit Daten, die USB-C-Buchse
  mit der Beschriftung für Programmieren/Strom am Board benutzen, nicht an einem Ladegerät oder Hub ohne Daten.
  Hilft das nicht: **BOOT gedrückt halten, USB anstecken, loslassen** (Download-Modus), dann flashen.
* **Keine LED, keine Reaktion auf Tasten, aber das Board ist erkannt:** im Monitor nach `IO-Expander TCA9555 nicht
  gefunden` suchen. Dann stimmt die I2C-Verdrahtung/Revision nicht mit `main/Board_Pins.h` überein. BOOT geht trotzdem.
  Beim Drücken einer Taste muss im Monitor `KEYS: Expander-Eingaenge: … KEY1(EXIO9)=0 …` erscheinen (0 = gedrückt). Erscheint
  nichts, kommt die Taste am Expander nicht an.
* **`Keine SD-Karte` obwohl eine steckt:** Karte FAT32 formatieren, ggf. andere Karte. Die SD-Daten-Leitung 3 liegt am
  IO-Expander (EXIO3) und wird beim Start hochgezogen; `STORAGE: … ESP_ERR_TIMEOUT` heißt „Karte antwortet nicht“.
* **Ring violett blinkend:** Mikrofon-Datenstrom steht. Neustart; tritt es wieder auf, Mikrofonverstärkung/Verdrahtung
  prüfen (`RECORD_VOLUME` in `main/Audio_Driver/Audio_Board.c`, Standard 33 dB, das Waveshare-Beispiel nutzt 30 dB).
* **Aufnahme zu leise:** Neue Aufnahmen werden automatisch angehoben (AGC, siehe oben); im Monitor zeigt
  `AGC-Gain x7.5`, wie stark. Reicht das nicht, `RECORD_VOLUME` erhöhen (Standard 33 dB, bis 37,5 dB). Zu hohe
  Analogverstärkung kann bei lautem, nahem Sprechen übersteuern.
* **Aufnahmen kommen nicht an:** Ring türkis statt grün → Empfänger läuft nicht oder falsche Adresse in
  `server_config.h`; im Monitor stehen `Upload FEHLER`-Zeilen mit dem Grund.

### Technische Daten (Pinbelegung)

I2C SDA 11 / SCL 10 · I2S MCLK 12, BCLK 13, WS 14, Mikrofone DIN 15, Lautsprecher DOUT 16 (nicht genutzt) ·
SD (SDMMC 1 Bit) CLK 40, CMD 42, D0 41, DAT3 = EXIO3 · LED-Ring (WS2812 ×7) GPIO 38 · Tasten KEY1–3 = EXIO 9–11
am TCA9555 (Adresse 0x20, aktiv low), BOOT = GPIO 0 · Verstärker-Enable EXIO8 bleibt aus.
Beim Aufnehmen sind auf dem Board noch ca. 40 KB internes RAM frei, die Last des Opus-Encoders liegt bei ca. 30 %
eines der zwei Kerne (gemessen auf dem S3 mit Bildschirm, gleicher Chip).
