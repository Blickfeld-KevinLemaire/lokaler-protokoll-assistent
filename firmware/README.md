# VERMERK-Recorder: Firmware für die ESP32-Aufnahmegeräte

Diese Firmware nimmt Besprechungen auf, speichert sie auf dem Gerät und lädt sie per WLAN an den PC
oder Server hoch, auf dem die Protokoll-Software (`protokoll_assistent/`) die Aufnahmen transkribiert.
Sie gehört **nicht** zur Windows-Anwendung und wird weder von der CI geprüft noch ausgeliefert.

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
Das Konzept mit Entscheidungen und Phasen steht in [`docs/streaming-konzept.md`](docs/streaming-konzept.md) (noch nicht umgesetzt).

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
* `main/Wireless/server_config.h.example` → `server_config.h` (Adresse des Empfängers, siehe unten)

## Gegenstelle

Die Geräte laden Aufnahmen per `POST /upload` hoch (Dateiname im Header `X-Filename`) und fragen
`GET /vermerk-status.txt` ab, um zu prüfen, ob die Gegenstelle erreichbar ist. Die Ordnerüberwachung der
Protokoll-Software nimmt `.wav`, `.mp3` und `.opus` an. **Achtung:** Jedes Gerät zählt seine Dateien selbst (H5_001, H5_002 …), mehrere Geräte können also dieselbe Nummer erreichen. Der Empfänger muss gleiche Namen unterscheiden und darf nie überschreiben; der Mini-Empfänger unten hängt dann _2, _3 … an. Ein Mini-Empfänger liegt als
[`tools/vermerk_receiver.py.txt`](tools/vermerk_receiver.py.txt) (zu `.py` umbenennen).

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
