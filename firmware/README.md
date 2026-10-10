# VERMERK-Recorder: Firmware für die ESP32-Aufnahmegeräte

Diese Firmware nimmt Besprechungen auf, speichert sie auf dem Gerät und lädt sie per WLAN an den PC
oder Server hoch, auf dem die Protokoll-Software (`protokoll_assistent/`) die Aufnahmen transkribiert.
Sie gehört **nicht** zur Windows-Anwendung und wird weder von der CI geprüft noch ausgeliefert.

| Ordner | Board | Chip | Aufnahme | Speicher |
|---|---|---|---|---|
| [`esp32-s3/`](esp32-s3/) | Waveshare ESP32-S3-Touch-LCD-1.85C | ESP32-S3, 2 Kerne, PSRAM | WAV, 16 kHz, 16 Bit, Stereo (2 Mikrofone) | SD-Karte |
| [`esp32-c6/`](esp32-c6/) | Waveshare ESP32-C6-Touch-LCD-1.83 | ESP32-C6, 1 Kern, kein PSRAM | MP3, 16 kHz, Mono, 32 kbit/s | Flash (ca. 13,8 MB, keine SD-Karte) |

Beide Versionen haben dieselbe Bedienung und dieselbe Aufnahme-, Pause- und Upload-Logik (`main/main.c`);
Treiber, Pinbelegung und Oberflächenlayout unterscheiden sich je nach Board. Der C6 zeigt außerdem den
USB-/Ladezustand direkt vom Power-Chip AXP2101 an, statt ihn aus der Akkuspannung zu erraten.

## Warum Mono, 16 kHz?

Die Protokoll-Software wandelt jede Eingabe vor der Transkription per ffmpeg in Mono, 16 kHz, 16 Bit um
(`services/ffmpeg_service.py`). Stereo und höhere Abtastraten kosten auf dem Gerät nur Speicherplatz.

## Bauen und flashen

ESP-IDF v5.5.x, jeweils im Ordner des Boards:

```
idf.py set-target esp32s3     # bzw. esp32c6
idf.py -p COMx build flash
```

Vorher die beiden Vorlagen kopieren und ausfüllen (die echten Dateien sind in `.gitignore` und kommen nie ins Repository):

* `main/Wireless/wifi_credentials.h.example` → `wifi_credentials.h` (WLAN-Name und Passwort)
* `main/Wireless/server_config.h.example` → `server_config.h` (Adresse des Empfängers, siehe unten)

## Gegenstelle

Die Geräte laden Aufnahmen per `POST /upload` hoch (Dateiname im Header `X-Filename`) und fragen
`GET /vermerk-status.txt` ab, um zu prüfen, ob die Gegenstelle erreichbar ist. Die Ordnerüberwachung der
Protokoll-Software nimmt `.wav`, `.mp3` und `.opus` an.

## Fremder Code

* `esp32-c6/components/shine/`: MP3-Encoder [shine](https://github.com/toots/shine), **LGPL-2.0** (siehe `COPYING`),
  mit den in der dortigen `README.md` beschriebenen Änderungen. Wird die Firmware weitergegeben, gelten die
  LGPL-Pflichten (Quelltext des Encoders und Änderungen bereitstellen).
* `esp32-c6/components/XPowersLib/`: [XPowersLib](https://github.com/lewisxhe/XPowersLib) (MIT), Treiber für den AXP2101.
* Teile der Treiber stammen aus den Beispielprojekten von Waveshare für die jeweiligen Boards
  ([ESP32-C6-Touch-LCD-1.83](https://github.com/waveshareteam/ESP32-C6-Touch-LCD-1.83)).
* LVGL, `esp_codec_dev`, `esp_lcd_touch` u. a. werden beim Bauen über den ESP-IDF-Komponentenmanager geladen
  und sind nicht im Repository.
