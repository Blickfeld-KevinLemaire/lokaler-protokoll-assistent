shine (https://github.com/toots/shine), Verzeichnis src/lib, Lizenz: GNU LGPL 2.0 (siehe COPYING).

Aenderungen gegenueber dem Original (Stand der Aenderung: Oktober 2026), alle fuer den ESP32-C6 ohne PSRAM:

* Die festen Rechentabellen (steptab, steptabi, int2idx; zusammen ca. 41 KB) liegen als const-Daten
  im Flash (src/shine_tables.c) statt im RAM. Die Formeln stehen im Kopf der Datei.
* MAX_CHANNELS=1 (siehe CMakeLists.txt): es wird nur Mono kodiert, das halbiert die Kanalpuffer.
* Neue Funktion shine_restart() (layer3.c/.h): setzt den Encoder fuer eine neue Datei zurueck, ohne den
  grossen Zustandsblock neu zu allokieren.
* Die fuer MIPS und ARM bestimmten mult_*-Header sind entfernt.
