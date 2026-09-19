# Lokaler Protokoll-Assistent

Transkribiert Besprechungsaufnahmen (mit Sprechertrennung) und erstellt
daraus anschliessend - als getrennter, unabhaengiger Schritt - mit einem
frei waehlbaren Sprachmodell ein Ergebnisdokument nach freier Wahl
(Zusammenfassung, Agenda, Prioritaetenliste, ...).

Sowohl die **Transkription** als auch die **Nachbearbeitung** verwenden
einen frei eintragbaren API-Endpunkt (Basis-URL), Modellnamen und
API-Schluessel - Standard ist jeweils OpenRouter (Transkription:
`microsoft/mai-transcribe-2` mit Azure-Sprechertrennung; Nachbearbeitung:
z. B. `openai/gpt-4o-mini`), es funktioniert aber ebenso mit einer direkten
Anbindung an Microsoft Azure oder jeden anderen Anbieter, der dasselbe
Anfrageformat versteht. Fuer die Nachbearbeitung steht zusaetzlich ein
**lokales** Modell (z. B. Ollama) zur Verfuegung, das keine Daten uebertraegt.

**Einstiegspunkt: `hauptanwendung.py`** - ein kleines Auswahlfenster, mit dem
Sie entscheiden, wie Sie arbeiten moechten, und das dann die passende
Anwendung startet:

- **Lokal (vollstaendig offline)** - startet `lokale_windows_app/`. Beim
  allerersten Mal laufen dort automatisch Systemtest und Modell-Download
  (siehe unten); eine Hardware-basierte Empfehlung schlaegt ein passendes
  Whisper-Modell vor, Sie entscheiden, welches tatsaechlich verwendet wird.
- **Schnittstelle nutzen (selbst eingerichtet)** - startet
  `protokoll_assistent_gui.py`. Sie richten dafuer selbst einen API-Zugang
  ein (aktuell: OpenRouter) und geben Ihren eigenen API-Schluessel ein.

`Protokoll-Assistent-Starten.bat` und die Desktop-Verknuepfung (siehe
[Installation](#installation-unter-windows-ein-fenster-fuer-alles)) oeffnen
dieses Auswahlfenster; Sie koennen die beiden Anwendungen darunter aber
auch jederzeit direkt starten, ohne den Umweg ueber `hauptanwendung.py`.

Es gibt drei unabhaengige Programme in diesem Repository:

- `protokoll_assistent_v2.py` - die bestehende Konsolenversion. Unveraendert,
  bleibt weiterhin eigenstaendig lauffaehig und dient gleichzeitig als
  Bibliothek fuer die GUI.
- `protokoll_assistent_gui.py` - die grafische Oberflaeche fuer die
  Cloud-Transkription (OpenRouter). Nutzt dieselbe Transkriptionslogik wie
  die Konsolenversion und ergaenzt die separate Nachbearbeitung per
  Systemprompt (lokal oder per API-Modell).
- **`lokale_windows_app/`** - eine komplett eigenstaendige, **vollstaendig
  lokale** Windows-Anwendung (WhisperX + pyannote.audio statt OpenRouter):
  keinerlei Cloud-/API-Anbindung, keine Uebertragung von Audio- oder
  Videodaten. Eigene GUI (PySide6), eigener Installationsweg, eigene
  Ausgabedateien. Siehe [`lokale_windows_app/README.md`](lokale_windows_app/README.md)
  fuer die vollstaendige Anleitung.

Alle drei Programme sind vollkommen unabhaengig voneinander lauffaehig und
beruehren sich gegenseitig nicht (keine gemeinsamen Dateien, keine
gemeinsamen Ordner).

### Welches Programm passt?

| | `protokoll_assistent_gui.py` (Cloud) | `lokale_windows_app/` (vollstaendig lokal) |
|---|---|---|
| Transkription | frei waehlbarer API-Endpunkt (Standard: OpenRouter / `microsoft/mai-transcribe-2`) | WhisperX (lokal, GPU empfohlen) |
| Sprechertrennung | ueber den gewaehlten Cloud-Anbieter | pyannote.audio (lokal) |
| Datenuebertragung | Audio wird an den gewaehlten Endpunkt gesendet | keine - alles laeuft auf dem Geraet |
| Nachbearbeitung | lokal (Ollama) oder frei waehlbarer API-Endpunkt | lokal (Ollama), dreistufig |
| Voraussetzungen | API-Schluessel fuer den gewaehlten Endpunkt, FFmpeg | Python, FFmpeg, optional NVIDIA-GPU (sonst CPU) |
| Installation | ein Fenster (siehe unten) | eigener Assistent, siehe `lokale_windows_app/README.md` |

Kurz: Wer keine Daten aus der Hand geben will (und eine ausreichend
schnelle GPU/CPU hat), nutzt `lokale_windows_app/`. Wer keine lokalen
KI-Modelle installieren moechte oder eine leistungsfaehige Cloud-
Transkription bevorzugt, nutzt `protokoll_assistent_gui.py`.

## Ordnerstruktur

```
eingabe/                                 Optionaler Startpunkt fuer den Ordnerdialog der GUI
ausgabe/                                 Volltranskript mit Sprechertrennung (TXT + JSON)
Ergebnis des Meetings wie gewuenscht/    Ergebnis der lokalen Nachbearbeitung (Zusammenfassung/Agenda/... als TXT + JSON)
zwischenstaende/                         Rohantworten der Cloud-Transkription (Wiederaufnahme nach Abbruch)
einstellungen/                           fachbegriffe.txt fuer Fachbegriffe/Eigennamen
```

`einstellungen/fachbegriffe.txt` wird **nicht** ins Repository aufgenommen, weil
dort Projektnamen und Nachnamen echter Personen stehen. Als Vorlage liegt
`einstellungen/fachbegriffe.beispiel.txt` bei - einmal nach `fachbegriffe.txt`
kopieren und ergaenzen.

Diese Ordner gehoeren zur Cloud-Variante (`protokoll_assistent_v2.py` /
`protokoll_assistent_gui.py`). `lokale_windows_app/` bringt eine eigene,
vollstaendig getrennte Ordnerstruktur mit (siehe dort) und teilt sich
nichts mit den obigen Ordnern.

Die Ordner werden beim Start automatisch angelegt, falls sie fehlen.

Der Projektordner selbst kann beliebig heissen und an einem beliebigen Ort
liegen (lokale Festplatte, USB-Stick, Netzlaufwerk, ...) - alle Skripte
ermitteln ihren Ordner automatisch anhand ihres eigenen Speicherorts. Jeder
Anwender kann sich also seinen eigenen Projektordner aussuchen, ohne Code
anpassen zu muessen.

## Installation unter Windows (ein Fenster fuer alles)

*Richtet die Cloud-Variante (`protokoll_assistent_gui.py`) ein und erstellt
eine Verknuepfung fuer `hauptanwendung.py` (das Auswahlfenster). Fuer die
vollstaendig lokale Variante siehe [`lokale_windows_app/README.md`](lokale_windows_app/README.md)
- dort gibt es einen eigenen, aehnlich aufgebauten Einrichtungsassistenten
(inkl. Systemtest und Whisper-Modellwahl), der beim ersten Start ueber die
Option "Lokal" im Auswahlfenster automatisch angestossen wird.*

Fuer Windows gibt es einen Einrichtungsassistenten, der die Schritte 1-4
uebernimmt bzw. anleitet:

1. Die Datei [`Protokoll-Assistent-Einrichten.bat`](Protokoll-Assistent-Einrichten.bat)
   herunterladen (z. B. ueber den "Raw"-Button auf GitHub, "Speichern unter ...").
2. Datei doppelklicken. Sie fragt nach dem gewuenschten Projektordner
   (Vorschlag: `%USERPROFILE%\Protokoll-Assistent`, aber jeder Anwender
   kann einen eigenen Ordner/Laufwerk eintragen - der gewaehlte Pfad wird
   fuer den naechsten Aufruf gemerkt), laedt das Projekt per `git` dorthin
   (Git wird bei Bedarf zur Installation vorgeschlagen), installiert das
   Paket fuer das moderne Erscheinungsbild und oeffnet danach automatisch
   das Einrichtungsfenster (`setup_fenster.py`).
3. Im Einrichtungsfenster werden Python, FFmpeg und das lokale KI-Modell
   (Ollama) geprueft. Fehlt etwas, oeffnet ein Klick die passende
   Download-Seite; das Modell laesst sich direkt per Knopfdruck laden.
4. Mit "Desktop-Verknuepfung erstellen" (Schritt 5) entsteht ein Icon auf
   dem Desktop, mit dem sich das Auswahlfenster (`hauptanwendung.py`)
   danach jederzeit per Doppelklick starten laesst (alternativ: "Anwendung
   jetzt starten" im selben Fenster, oder direkt
   `Protokoll-Assistent-Starten.bat`). Von dort aus starten Sie dann
   entweder die Cloud-Variante oder - beim ersten Mal inklusive
   automatischer Einrichtung - die vollstaendig lokale Variante.

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
- Fuer die Transkription: ein API-Schluessel fuer den gewaehlten Endpunkt
  (Standard: OpenRouter, `https://openrouter.ai/api/v1/audio/transcriptions`
  mit Modell `microsoft/mai-transcribe-2` und Anbieter `azure` fuer die
  Sprechertrennung). Endpunkt, Modell und Anbieter sind in der GUI frei
  aenderbar; Standardwerte auch per Umgebungsvariable vorbelegbar:
  `PROTOKOLL_TRANSKRIPTION_ENDPUNKT`, `PROTOKOLL_TRANSKRIPTION_MODELL`,
  `PROTOKOLL_TRANSKRIPTION_ANBIETER`.
- Fuer die Nachbearbeitung des Transkripts, je nach gewaehlter Option:
  - **Lokal**: ein lokales KI-Modell, z. B. [Ollama](https://ollama.com).
    Nach der Installation ein Modell laden, z. B.:
    ```
    ollama pull llama3.1
    ```
    Ollama muss beim Start der Nachbearbeitung laufen (Standard:
    `http://localhost:11434`). Adresse und Modellname lassen sich per
    Umgebungsvariable anpassen: `PROTOKOLL_LOKALES_MODELL_URL`,
    `PROTOKOLL_LOKALES_MODELL`.
  - **API-Modell**: keine zusaetzliche Installation noetig. Endpunkt
    (Basis-URL), Modellname und API-Schluessel sind frei eintragbar -
    Standard ist OpenRouters `/chat/completions`-Endpunkt (Modell z. B.
    `openai/gpt-4o-mini`, `anthropic/claude-3.5-sonnet`), es funktioniert
    aber mit jedem Anbieter, der dieselbe OpenAI-kompatible Schnittstelle
    bereitstellt (z. B. `https://api.openai.com/v1/chat/completions` bei
    OpenAI oder der entsprechende Endpunkt bei IONOS AI Model Hub - Details
    beim jeweiligen Anbieter nachschlagen). Standardwerte per
    Umgebungsvariable vorbelegbar: `PROTOKOLL_API_ENDPUNKT`,
    `PROTOKOLL_API_MODELL`.
- Optional fuer ein moderneres Erscheinungsbild (Windows-11-Stil, Light/Dark):
  `pip install -r requirements.txt` (installiert `sv-ttk`). Fehlt das Paket,
  startet die GUI trotzdem, dann mit einem schlichteren Standard-ttk-Design.

## API-Schluessel

API-Schluessel werden **niemals** im Code gespeichert.

- Konsolenversion (fest auf OpenRouter eingestellt): Umgebungsvariable
  `OPENROUTER_API_KEY` setzen, bevor das Skript gestartet wird.
- GUI: Schluessel in die dafuer vorgesehenen Felder eintragen (Transkription,
  und optional ein eigener fuer die Nachbearbeitung bei einem anderen
  Endpunkt). Sie werden nur fuer die Dauer der Sitzung im Arbeitsspeicher
  gehalten und nicht auf die Festplatte geschrieben.

## GUI benutzen

```
python3 protokoll_assistent_gui.py
```

Transkription und Nachbearbeitung sind zwei getrennte Schritte, die auch
zeitlich unabhaengig voneinander laufen koennen:

**A) Transkription**
1. Ordner auswaehlen, in dem die Aufnahme liegt (bei mehreren passenden
   Dateien im Ordner erscheint eine Auswahlliste).
2. API-Schluessel eintragen. Endpunkt (Basis-URL), Modellname und Anbieter
   (fuer die Sprechertrennung) sind voreingestellt auf OpenRouter /
   `microsoft/mai-transcribe-2` / `azure`, aber frei aenderbar - z. B. fuer
   eine direkte Anbindung an Microsoft Azure oder einen anderen Anbieter,
   der dasselbe Anfrageformat (JSON mit Base64-Audio) versteht. "Anbieter"
   leer lassen, wenn der Endpunkt keine Provider-Weiterleitung fuer die
   Sprechertrennung benoetigt.
3. "Transkription starten" klicken.

Nach Abschluss wird das fertige Transkript automatisch in Schritt 3 der
Nachbearbeitung (siehe unten) eingetragen.

**B) Nachbearbeitung** (jederzeit, auch fuer ein frueher erstelltes
Transkript - unabhaengig von einer aktuellen Transkription):
1. Transkript auswaehlen (wird nach einer Transkription automatisch
   eingetragen, oder manuell aus `ausgabe/` auswaehlen).
2. Sprachmodell waehlen:
   - **Lokal** (z. B. Ollama) - das Transkript verlaesst dabei das Geraet nicht.
   - **API-Modell** (frei waehlbarer Endpunkt) - Endpunkt (Basis-URL) und
     Modellname eintragen (Standard: OpenRouter, ebenso moeglich z. B.
     OpenAI, IONOS AI Model Hub, ...). Fuer den API-Schluessel gibt es ein
     eigenes Feld direkt daneben; leer gelassen wird der API-Schluessel aus
     Schritt A wiederverwendet (nur sinnvoll, wenn dort ebenfalls OpenRouter
     verwendet wird). Das Transkript wird dabei an den eingetragenen
     Endpunkt uebertragen.
3. Im Systemprompt-Feld beschreiben, was mit dem Transkript geschehen soll
   (Vorlagen fuer Zusammenfassung/Agenda/Prioritaetenliste stehen bereit,
   oder freier Text fuer jede andere Aufgabe).
4. "Nachbearbeitung starten" klicken.

Vor jeder Uebertragung nach aussen (Transkription an OpenRouter/Azure, oder
Nachbearbeitung mit einem API-Modell) erscheint eine Datenschutzabfrage,
die bestaetigt werden muss. Bei lokaler Nachbearbeitung entfaellt das, da
keine Daten das Geraet verlassen.

Beide Schritte laufen im Hintergrund (eigener Thread); Fortschrittsbalken
und Protokollbereich zeigen den aktuellen Stand an.

### Ausgabedateien

- in `ausgabe/`: `<name>_mai2_transkript.txt` / `.json` - vollstaendiges
  Transkript mit Sprechertrennung (identisch zur Konsolenversion)
- in `Ergebnis des Meetings wie gewuenscht/`: `<name>_protokoll.txt` / `.json`
  - das Ergebnis der Nachbearbeitung gemaess Systemprompt (Zusammenfassung,
  Agenda, Prioritaetenliste, ...), inkl. Angabe, ob lokal oder per API-Modell
  erzeugt

## Sprecher mit echten Namen versehen (GUI)

Die Cloud-Diarisierung liefert nur technische Bezeichnungen ("Sprecher 1",
"Sprecher 2", ...). Wenn sich die Teilnehmer zu Beginn der Aufnahme kurz
vorstellen ("Hallo, ich bin Fritz." / "Mein Name ist Marco." / "Hier
spricht Julia."), kann die GUI diese Selbstvorstellungen automatisch
erkennen und die Bezeichnungen im ganzen Transkript entsprechend ersetzen:

1. Nach jeder Transkription (Haekchen "Sprecher danach benennen", per
   Standard aktiviert) durchsucht die App die ersten
   `PROTOKOLL_SPRECHER_FENSTER_MINUTEN` Minuten (Standard: 3) nach Mustern
   wie "ich bin ...", "ich heisse ...", "mein Name ist ..." oder "hier
   spricht/ist ...".
2. Ein Dialogfenster zeigt pro erkanntem Sprecher ein Textbeispiel und ein
   vorausgefuelltes Namensfeld (falls eine Vorstellung erkannt wurde).
   Namen lassen sich dort pruefen, korrigieren oder ergaenzen; leer
   gelassene Felder behalten die technische Bezeichnung.
3. Nach "Uebernehmen" wird der Name im gesamten Transkript verwendet -
   auch in Segmenten weit nach der Vorstellung, da die Zuordnung pro
   Sprecher-ID gilt, nicht nur innerhalb des Zeitfensters.

Der Button "Sprecher umbenennen ..." (bei Punkt 3, Transkript auswaehlen)
oeffnet denselben Dialog jederzeit erneut fuer ein beliebiges vorhandenes
Transkript - unabhaengig davon, ob die automatische Erkennung beim Erstellen
etwas gefunden hat oder uebersprungen wurde.

Die Erkennung ist eine Texterkennung per Muster, kein echtes
Stimm-Erkennungsverfahren: Sie schlaegt nur Namen vor, wenn eine passende
Formulierung im Transkript steht. Ohne (oder bei unklarer) Selbstvorstellung
bleibt das Namensfeld leer und die technische Bezeichnung wird beibehalten.

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

## Fuer die Weiterentwicklung (Tests, Linting, CI)

Dieser Abschnitt richtet sich an alle, die am Code selbst arbeiten. Fuer die
reine Benutzung der Anwendung wird davon nichts gebraucht - die Installation
laeuft weiterhin ueber `Protokoll-Assistent-Einrichten.bat` bzw.
`lokale_windows_app/setup_lokal.ps1`.

### Einmalig einrichten

Die Entwicklungswerkzeuge werden mit [uv](https://docs.astral.sh/uv/)
verwaltet (`pyproject.toml` + `uv.lock`):

```powershell
winget install --id=astral-sh.uv       # falls uv noch fehlt
uv sync --python 3.11
```

Das legt eine `.venv` an - getrennt von der `.venv-whisperx`, in der die
KI-Pakete (PyTorch, WhisperX, pyannote) liegen. Diese schweren Pakete sind
bewusst **nicht** Teil der Entwicklungsumgebung: die Tests ersetzen sie
durchgehend, damit sie ohne GPU in Sekunden laufen.

### Die drei Befehle

```powershell
uv run ruff check .      # Linting (mit --fix werden viele Funde direkt behoben)
uv run mypy              # Typpruefung
uv run pytest            # Tests inklusive Abdeckungsmessung
```

`uv run pytest` bricht ab, wenn die Testabdeckung unter 85 % faellt. Einen
ausfuehrlichen Bericht als Webseite gibt es mit:

```powershell
uv run pytest --cov-report=html
start htmlcov/index.html
```

### Was auf GitHub automatisch laeuft

| Wann | Was |
|---|---|
| Bei jedem Push und Pull Request (`.github/workflows/ci.yml`) | Linting und Typpruefung (Linux), Tests unter Windows mit Python 3.10 **und** 3.11, Suche nach Zugangsdaten (gitleaks), Schwachstellenpruefung der Abhaengigkeiten (pip-audit) |
| Jede Nacht (`.github/workflows/nightly.yml`) | Schwachstellenpruefung; zusaetzlich Tests und ein PyInstaller-Probelauf, falls es am Vortag Aenderungen gab |
| Bei einem Versions-Tag `v*` (`.github/workflows/release.yml`) | Windows-Build und Veroeffentlichung als GitHub-Release |
| Montags (`.github/dependabot.yml`) | Dependabot schlaegt Aktualisierungen der Abhaengigkeiten vor |

Die Tests laufen unter Windows, weil die Anwendung nur dort eingesetzt wird.
Linux-Laeufer verbrauchen weniger vom monatlichen Actions-Kontingent und
uebernehmen deshalb die plattformunabhaengigen Pruefungen.

### Wissenswertes

* **Zeilenenden:** `.gitattributes` legt LF fest. Ohne das schreiben
  Windows-Werkzeuge CRLF zurueck, und jede kleine Aenderung erscheint als
  komplett neu geschriebene Datei.
* **Fenstertests:** Die Tests oeffnen echte tkinter- und Qt-Fenster. Qt laeuft
  dabei unsichtbar (`QT_QPA_PLATFORM=offscreen`).
* **Geheimnisse:** Kein API-Schluessel und kein Hugging-Face-Token gehoert in
  das Repository. Die Tests loeschen entsprechende Umgebungsvariablen
  vorsorglich, und gitleaks prueft in der CI auch die Versionsgeschichte.
