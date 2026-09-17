# Lokaler Protokoll-Assistent

Transkribiert Besprechungsaufnahmen (mit Sprechertrennung, ueber OpenRouter /
`microsoft/mai-transcribe-2`) und erstellt daraus anschliessend mit einem
**lokalen** KI-Modell ein Ergebnisdokument nach freier Wahl (Zusammenfassung,
Agenda, Prioritaetenliste, ...).

Es gibt zwei gleichwertige, unabhaengige Programme:

- `protokoll_assistent_v2.py` - die bestehende Konsolenversion. Unveraendert,
  bleibt weiterhin eigenstaendig lauffaehig und dient gleichzeitig als
  Bibliothek fuer die GUI.
- `protokoll_assistent_gui.py` - die neue grafische Oberflaeche. Nutzt dieselbe
  Transkriptionslogik wie die Konsolenversion und ergaenzt die lokale
  Nachbearbeitung per Systemprompt.

## Ordnerstruktur

```
eingabe/                                 Optionaler Startpunkt fuer den Ordnerdialog der GUI
ausgabe/                                 Volltranskript mit Sprechertrennung (TXT + JSON)
Ergebnis des Meetings wie gewuenscht/    Ergebnis der lokalen Nachbearbeitung (Zusammenfassung/Agenda/... als TXT + JSON)
zwischenstaende/                         Rohantworten der Cloud-Transkription (Wiederaufnahme nach Abbruch)
einstellungen/                           fachbegriffe.txt fuer Fachbegriffe/Eigennamen
```

Die Ordner werden beim Start automatisch angelegt, falls sie fehlen.

Der Projektordner selbst kann beliebig heissen und an einem beliebigen Ort
liegen (lokale Festplatte, USB-Stick, Netzlaufwerk, ...) - alle Skripte
ermitteln ihren Ordner automatisch anhand ihres eigenen Speicherorts. Jeder
Anwender kann sich also seinen eigenen Projektordner aussuchen, ohne Code
anpassen zu muessen.

## Installation unter Windows (ein Fenster fuer alles)

Fuer Windows gibt es einen Einrichtungsassistenten, der die Schritte 1-4
uebernimmt bzw. anleitet:

1. Die Datei [`Protokoll-Assistent-Einrichten.bat`](Protokoll-Assistent-Einrichten.bat)
   herunterladen (z. B. ueber den "Raw"-Button auf GitHub, "Speichern unter ...").
2. Datei doppelklicken. Sie fragt nach dem gewuenschten Projektordner
   (Vorschlag: `%USERPROFILE%\Protokoll-Assistent`, aber jeder Anwender
   kann einen eigenen Ordner/Laufwerk eintragen - der gewaehlte Pfad wird
   fuer den naechsten Aufruf gemerkt), laedt das Projekt per `git` dorthin
   (Git wird bei Bedarf zur Installation vorgeschlagen) und oeffnet danach
   automatisch das Einrichtungsfenster (`setup_fenster.py`).
3. Im Einrichtungsfenster werden Python, FFmpeg und das lokale KI-Modell
   (Ollama) geprueft. Fehlt etwas, oeffnet ein Klick die passende
   Download-Seite; das Modell laesst sich direkt per Knopfdruck laden.
4. Mit "Desktop-Verknuepfung erstellen" (Schritt 5) entsteht ein Icon auf
   dem Desktop, mit dem sich `protokoll_assistent_gui.py` danach jederzeit
   per Doppelklick starten laesst (alternativ: "Anwendung jetzt starten"
   im selben Fenster, oder direkt `Protokoll-Assistent-Starten.bat`).

Auf macOS/Linux die Voraussetzungen unten manuell installieren und die GUI
wie im Abschnitt "GUI benutzen" beschrieben starten.

## Voraussetzungen

- Python 3.10 oder neuer
- Fuer die GUI: das Modul `tkinter` (gehoert bei den meisten Python-Installationen
  dazu; unter Debian/Ubuntu ggf. nachinstallieren mit
  `sudo apt install python3-tk`)
- **FFmpeg** fuer Videos oder grosse Audiodateien (alles ausser kleinen MP3s).
  Die GUI sucht FFmpeg automatisch: zuerst in `PATH`, danach in den ueblichen
  Installationsordnern (`/usr/bin`, `/usr/local/bin`, `/opt/homebrew/bin`,
  Standard-Windows-Pfade) und ueber die Umgebungsvariable `FFMPEG_PATH`. Wird
  FFmpeg gefunden, aber ist nicht in `PATH`, wird es fuer die laufende Sitzung
  automatisch ergaenzt. Download: https://ffmpeg.org/download.html
- Ein **lokales** KI-Modell fuer die Nachbearbeitung des Transkripts, z. B.
  [Ollama](https://ollama.com). Nach der Installation ein Modell laden, z. B.:
  ```
  ollama pull llama3.1
  ```
  Ollama muss beim Start der GUI laufen (Standard: `http://localhost:11434`).
  Adresse und Modellname lassen sich per Umgebungsvariable anpassen:
  `PROTOKOLL_LOKALES_MODELL_URL`, `PROTOKOLL_LOKALES_MODELL`.

## API-Schluessel

Der OpenRouter API-Schluessel wird **niemals** im Code gespeichert.

- Konsolenversion: Umgebungsvariable `OPENROUTER_API_KEY` setzen, bevor das
  Skript gestartet wird.
- GUI: Schluessel in das dafuer vorgesehene Feld eintragen. Er wird nur fuer
  die Dauer der Sitzung im Arbeitsspeicher gehalten und nicht auf die
  Festplatte geschrieben.

## GUI benutzen

```
python3 protokoll_assistent_gui.py
```

1. Ordner auswaehlen, in dem die Aufnahme liegt (bei mehreren passenden
   Dateien im Ordner erscheint eine Auswahlliste).
2. OpenRouter API-Schluessel eintragen.
3. Namen des lokalen Modells pruefen/anpassen.
4. Im Systemprompt-Feld beschreiben, was mit dem Transkript geschehen soll
   (Vorlagen fuer Zusammenfassung/Agenda/Prioritaetenliste stehen bereit).
5. "Transkription starten" klicken.

Vor jeder Uebertragung an OpenRouter/den Modellanbieter erscheint eine
Datenschutzabfrage, die bestaetigt werden muss. Die anschliessende
Auswertung durch das lokale Modell verlaesst das Geraet nicht.

Der Ablauf laeuft im Hintergrund (eigener Thread), waehrenddessen zeigen
Fortschrittsbalken und Protokollbereich den aktuellen Schritt an:
Vorbereitung -> Uebertragung -> Sprechertrennung/Speichern -> lokale
Nachbearbeitung -> Fertig.

### Ausgabedateien

- in `ausgabe/`: `<name>_mai2_transkript.txt` / `.json` - vollstaendiges
  Transkript mit Sprechertrennung (identisch zur Konsolenversion)
- in `Ergebnis des Meetings wie gewuenscht/`: `<name>_protokoll.txt` / `.json`
  - das eigentliche Ergebnis der lokalen Nachbearbeitung gemaess
  Systemprompt (Zusammenfassung, Agenda, Prioritaetenliste, ...)

## Konsolenversion benutzen

```
export OPENROUTER_API_KEY=...
python3 protokoll_assistent_v2.py
```

Erwartet genau eine Audio-/Videodatei im Ordner `eingabe/` (bei mehreren
Dateien wird interaktiv nachgefragt). Diese Datei bleibt unveraendert und
wird durch die GUI nicht ueberschrieben.

## Verarbeitung langer Aufnahmen (GUI)

Kurze und mittellange Aufnahmen werden in einem Durchgang uebertragen
(inkl. Sprechertrennung), damit Sprecher-IDs innerhalb der Aufnahme stabil
bleiben. Das reicht in der Regel bis knapp unter eine Stunde.

Fuer laengere Aufnahmen (Standard-Schwelle: **40 Minuten**, z. B. eine bis
zu 2 Stunden lange Besprechung) teilt die GUI die Aufnahme automatisch in
Abschnitte auf (Standard: **15 Minuten** je Abschnitt), transkribiert jeden
Abschnitt einzeln und fuegt das Ergebnis danach zeitlich sortiert wieder zu
einem durchgaengigen Transkript zusammen (`<name>_mai2_transkript.txt/json`
in `ausgabe/`, wie gewohnt). Das geschieht automatisch im Hintergrund;
nichts muss manuell aufgeteilt oder wieder zusammengefuegt werden. Auch bei
einem Abbruch mitten in einer langen Aufnahme werden bereits fertig
transkribierte Abschnitte beim naechsten Versuch nicht erneut hochgeladen
(Wiederaufnahme ueber `zwischenstaende/`, wie beim regulaeren Ablauf).

**Wichtige Einschraenkung:** Die Sprechertrennung laeuft pro Abschnitt
unabhaengig - ob "Sprecher 1" in Abschnitt 2 dieselbe Person ist wie
"Sprecher 1" in Abschnitt 1, kann ueber getrennte Cloud-Anfragen hinweg
nicht garantiert werden. Deshalb tragen alle Sprecherbezeichnungen in
aufgeteilten Transkripten den Zusatz `(Teil N)`, statt eine durchgehende
Identitaet vorzutaeuschen.

Schwelle und Abschnittslaenge lassen sich per Umgebungsvariable anpassen:
`PROTOKOLL_CHUNK_SCHWELLE_MINUTEN` (Standard 40),
`PROTOKOLL_CHUNK_LAENGE_MINUTEN` (Standard 15). Das Aufteilen benoetigt
FFmpeg (siehe oben) sowie `ffprobe` (liegt bei jeder Standard-FFmpeg-
Installation bei).

Die Konsolenversion (`protokoll_assistent_v2.py`) teilt Aufnahmen bewusst
nicht auf und bleibt unveraendert.
