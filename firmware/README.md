# VERMERK-Recorder: Firmware für die ESP32-Aufnahmegeräte

Diese Firmware nimmt Besprechungen auf, speichert sie auf dem Gerät und lädt sie per WLAN an den PC
oder Server hoch, auf dem die Protokoll-Software (`protokoll_assistent/`) die Aufnahmen transkribiert.
Sie gehört **nicht** zur Windows-Anwendung und wird weder von der CI geprüft noch ausgeliefert.

| Ordner | Board | Chip | Aufnahme | Speicher |
|---|---|---|---|---|
| [`esp32-s3/`](esp32-s3/) | Waveshare ESP32-S3-Touch-LCD-1.85C | ESP32-S3, 2 Kerne, PSRAM | WAV, 16 kHz, 16 Bit, Stereo (2 Mikrofone) | SD-Karte |
| [`esp32-c6/`](esp32-c6/) | Waveshare ESP32-C6-Touch-LCD-1.83 | ESP32-C6, 1 Kern, kein PSRAM | Ogg-Opus (`.opus`), 16 kHz, Mono, 24 kbit/s (umschaltbar auf MP3) | Flash (ca. 13,8 MB, keine SD-Karte) |

Beide Versionen haben dieselbe Bedienung und dieselbe Aufnahme-, Pause- und Upload-Logik (`main/main.c`);
Treiber, Pinbelegung und Oberflächenlayout unterscheiden sich je nach Board. Der C6 zeigt außerdem den
USB-/Ladezustand direkt vom Power-Chip AXP2101 an, statt ihn aus der Akkuspannung zu erraten.

## Warum Mono, 16 kHz?

Die Protokoll-Software wandelt jede Eingabe vor der Transkription per ffmpeg in Mono, 16 kHz, 16 Bit um
(`services/ffmpeg_service.py`). Stereo und höhere Abtastraten kosten auf dem Gerät nur Speicherplatz.

## Aufnahmeformat und Speicher auf dem C6

Das Board hat keine SD-Karte; Aufnahmen liegen in einer FAT-Partition im Flash (ca. 13,8 MB). Nach dem Hochladen
löscht das Gerät die Datei wieder. Die Bitrate steht in `esp32-c6/main/Opus_Encoder/Opus_Encoder.h`
(`OPUS_BITRATE_BPS`), das Format in `esp32-c6/main/Rec_Codec.h` (`REC_CODEC_OPUS 1` = Opus, `0` = MP3):

| Bitrate | pro Stunde | Aufnahmezeit auf 13,8 MB |
|---|---|---|
| 16 kbit/s | 7,2 MB | ca. 115 min |
| 24 kbit/s (Standard) | 10,8 MB | ca. 77 min |
| 32 kbit/s | 14,4 MB | ca. 58 min |

Messung mit dem Whisper der Protokoll-Software (large-v3-turbo) an vier echten Aufnahmen: Bei sauberer Sprache ist
selbst 12 kbit/s unauffällig; bei schlechtem Material (Rauschen, Abstand zum Mikrofon) wächst die Abweichung
vom Transkript des unkomprimierten Originals unterhalb von 24 kbit/s spürbar. Die Stichprobe ist klein, die
Streuung von Whisper selbst liegt bei einigen Prozent.

Der C6 hat keinen PSRAM. Damit Aufnahme, Encoder und Upload gleichzeitig laufen, ist der RAM bewusst knapp
bemessen (Encoder ca. 25 KB, Encoder-Stack 28 KB, kleine Display- und Upload-Puffer, nur ein I2S-Aufnahmekanal).
Der Encoder muss früh in `app_main` angelegt werden, solange noch ein großer zusammenhängender Block frei ist.

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
* Opus-Encoder: Komponente `espressif/esp_audio_codec` (wird beim Bauen geladen, nicht im Repository). Ihre Lizenz
  (Espressif Modified MIT) erlaubt die Nutzung nur auf Espressif-Chips; das trifft hier zu.
* `esp32-c6/components/XPowersLib/`: [XPowersLib](https://github.com/lewisxhe/XPowersLib) (MIT), Treiber für den AXP2101.
* Teile der Treiber stammen aus den Beispielprojekten von Waveshare für die jeweiligen Boards
  ([ESP32-C6-Touch-LCD-1.83](https://github.com/waveshareteam/ESP32-C6-Touch-LCD-1.83)).
* LVGL, `esp_codec_dev`, `esp_lcd_touch` u. a. werden beim Bauen über den ESP-IDF-Komponentenmanager geladen
  und sind nicht im Repository.
