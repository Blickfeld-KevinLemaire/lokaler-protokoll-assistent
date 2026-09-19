# Protokoll-Assistent Lokal

Vollständig lokale Windows-Desktop-Anwendung zur Transkription, Sprecher­trennung
und Protokollerstellung für Audio- und Videoaufnahmen — **ohne jede
Cloud-/API-Anbindung**. Es werden keine Audio- oder Videodaten übertragen.

Diese Anwendung ist ein **eigenständiges, separates Paket**. Sie verwendet
NICHT die vorhandene Datei `protokoll_assistent_v2.py` (OpenRouter-Version)
und verändert diese auch nicht. Beide Programme können unabhängig
nebeneinander bestehen.

**Für jeden PC, nicht nur für einen bestimmten Rechner:** Die Anwendung
prüft beim Start selbst, was auf dem jeweiligen Computer bereits vorhanden
ist, und richtet fehlende Programme/Modelle automatisch ein — Sie müssen
vorher nichts manuell installieren außer Python selbst (siehe
[Voraussetzungen](#voraussetzungen)). Ist bereits eine vollständig
eingerichtete `.venv-whisperx` vorhanden (z.B. auf dem ursprünglichen
Referenzrechner), wird diese automatisch erkannt und weiterverwendet.

> **Datenschutz:** *„Die Verarbeitung erfolgt vollständig lokal auf diesem
> Computer. Es werden keine Audio- oder Videodaten übertragen."* Dieser
> Hinweis wird auch in der Anwendung selbst prominent angezeigt.

---

## Inhalt

1. [So funktioniert der erste Start](#so-funktioniert-der-erste-start)
2. [Voraussetzungen](#voraussetzungen)
3. [Ordnerstruktur](#ordnerstruktur)
4. [Installation — Schritt für Schritt](#installation--schritt-für-schritt)
5. [Bedienung der Anwendung](#bedienung-der-anwendung)
6. [Ausgabedateien](#ausgabedateien)
6a. [Verfügbare Whisper-Modelle](#verfügbare-whisper-modelle)
7. [Langzeitaufnahmen (Chunking, Fortsetzen)](#langzeitaufnahmen-chunking-fortsetzen)
8. [Lokale Protokollerstellung (Ollama)](#lokale-protokollerstellung-ollama)
9. [Windows-Build (EXE)](#windows-build-exe)
10. [Fortgeschrittener/manueller Einrichtungsweg](#fortgeschrittenermanueller-einrichtungsweg)
11. [Tests](#tests)
12. [Fehlerbehandlung / Problembehebung](#fehlerbehandlung--problembehebung)
13. [Was hier bereits geprüft wurde und was Sie selbst prüfen müssen](#was-hier-bereits-geprüft-wurde-und-was-sie-selbst-prüfen-müssen)

---

## So funktioniert der erste Start

Die Anwendung ist als moderner, selbsterklärender Einrichtungsassistent
aufgebaut — ähnlich wie man es von heutiger Desktop-Software gewohnt ist:

1. **Anwendung starten** (`Start-Protokoll-Assistent.ps1` oder `app.py`).
   Fehlt noch eine passende Python-Laufzeitumgebung, richtet sich die
   Anwendung **automatisch selbst ein**: sie legt eine eigene, private
   Umgebung an (`runtime\venv`) und installiert dort PyTorch passend zur
   erkannten Grafikkarte (oder für reinen CPU-Betrieb, falls keine
   NVIDIA-GPU gefunden wird), WhisperX, pyannote.audio, PySide6 usw. Dabei
   erscheint ein kleines Fortschrittsfenster mit Protokoll — das kann beim
   allerersten Mal je nach Internetverbindung einige Minuten dauern.
2. Danach öffnet sich der **Einrichtungsassistent** in der Anwendung selbst:
   - **Willkommen** — kurze Erklärung und Datenschutzhinweis.
   - **Einrichtung** — fehlendes FFmpeg und/oder Ollama werden automatisch
     heruntergeladen, danach das pyannote-Modell und das Ollama-Modell.
   - **Systemtest** — zeigt übersichtlich, ob alles vorhanden und
     einsatzbereit ist (Python, GPU/CPU, VRAM, RAM, FFmpeg, Modelle,
     Ollama, ...).
   - **Modell** — anhand der beim Systemtest erkannten Hardware (VRAM bzw.
     Arbeitsspeicher) wird ein passendes Whisper-Modell **vorgeschlagen**;
     Sie sehen alle verfügbaren Modelle (siehe
     [Verfügbare Whisper-Modelle](#verfügbare-whisper-modelle)) und
     entscheiden selbst, welches heruntergeladen und verwendet wird.
   - **Eingabeordner** — Sie wählen einmalig den Ordner mit Ihren
     Aufnahmen; unterstützte Dateien darin werden sofort aufgelistet.
3. Danach öffnet sich das **Hauptfenster** und Sie können direkt eine Datei
   auswählen und die Verarbeitung starten. Das Whisper-Modell lässt sich
   dort jederzeit über das Dropdown "Whisper-Modell" ändern (auch nach der
   Ersteinrichtung), die Wahl wird gemerkt.

Der zuletzt verwendete Eingabe-/Ausgabeordner wird lokal in
`konfiguration.json` gemerkt (keine Zugangsdaten, keine Rechnernamen) —
beim nächsten Start ist er bereits vorausgewählt.

---

## Voraussetzungen

Einzige echte Voraussetzung auf einem **neuen** PC:

- Windows, mit **Python 3.10 oder 3.11** installiert
  (<https://www.python.org/downloads/> — beim Installieren „Add python.exe
  to PATH" aktivieren).

Alles Weitere (FFmpeg, PyTorch, WhisperX, pyannote.audio, PySide6, Ollama
inkl. Modell) wird von der Anwendung selbst automatisch eingerichtet, wie
oben beschrieben. Für gute Geschwindigkeit wird eine NVIDIA-GPU mit
aktuellem Treiber empfohlen (erfolgreich getestet z.B. mit RTX 3060 Ti,
CUDA 12.8) — **zwingend** ist das aber nicht: ohne nutzbare GPU verarbeitet
die Anwendung auf der CPU weiter (deutlich langsamer, aber funktionsfähig).

### Welche Grafikkarten beschleunigen?

| Karte | Beschleunigung | Woher PyTorch kommt |
|---|---|---|
| NVIDIA bis Ada/Hopper (Rechenfähigkeit < 12.0) | ja | Index `cu126` |
| NVIDIA Blackwell (RTX 50xx, RTX PRO, Rechenfähigkeit ≥ 12.0) | ja | Index `cu129` |
| AMD, Intel, keine Grafikkarte | nein — CPU | Index `cpu` |

Die Anwendung fragt die Rechenfähigkeit beim Treiber ab (`nvidia-smi`) und
wählt den passenden Index selbst. Das ist nötig, weil **kein einziger
CUDA-Index alle Karten bedient**: Blackwell-Kernel (`sm_120`) gibt es erst
ab CUDA 12.8, ältere Karten fallen in den neuen Indizes dagegen weg.

**AMD-Grafikkarten können hier nicht beschleunigen**, und das lässt sich
auch nicht nachrüsten:

1. PyTorch bietet ROCm (den AMD-Weg) **ausschließlich für Linux** an — für
   Windows gibt es keine einzige ROCm-Paketdatei.
2. Selbst mit PyTorch wäre nichts gewonnen: Die eigentliche Transkription
   läuft über faster-whisper und damit über CTranslate2, und das
   unterstützt nur CPU und CUDA.

Auf AMD-Rechnern läuft die Anwendung deshalb vollständig, aber auf der CPU.
Die Anwendung sagt das auch so: „keine nutzbare NVIDIA-GPU erkannt
(CPU-Verarbeitung; GPU-Beschleunigung ist nur mit NVIDIA/CUDA möglich)".

Ob die GPU wirklich rechnen kann, wird **nicht** allein an
`torch.cuda.is_available()` festgemacht: Passt der CUDA-Build nicht zur
Kartengeneration, meldet das fälschlich `True`, und erst die erste echte
Rechnung scheitert — mitten in der Transkription. Die Anwendung rechnet
deshalb einmal kurz zur Probe und wechselt sonst sauber auf die CPU.

Für die lokale Protokollerstellung zusätzlich empfohlen: [Ollama](https://ollama.com)
mit dem Modell `qwen3:8b` — wird ebenfalls automatisch heruntergeladen bzw.
der Installer angeboten, falls Ollama fehlt.

**Referenzrechner mit bereits vorhandener `.venv-whisperx`:** Wurde auf
diesem PC bereits manuell eine virtuelle Umgebung mit WhisperX 3.8.6,
PyTorch 2.8.0+cu128, CUDA 12.8 und pyannote.audio eingerichtet und liegt sie
NEBEN dem Anwendungsordner, erkennt die Anwendung dies automatisch und
verwendet sie direkt weiter (kein erneuter Download):

```text
protokoll-assistent\
    .venv-whisperx\
    protokoll_assistent_v2.py          (OpenRouter-Version — unverändert)
    lokale_windows_app\                (dieses Paket)
        app.py
        ...
```

Auf jedem anderen PC ohne diese Struktur legt die Anwendung stattdessen
automatisch `lokale_windows_app\runtime\venv` an — der Speicherort spielt
für die Bedienung keine Rolle.

---

## Ordnerstruktur

```text
lokale_windows_app\
    app.py                          Einstiegspunkt (ruft zuerst bootstrap.py auf)
    bootstrap.py                    Selbstinstallierende Laufzeitumgebung
    gui\                            PySide6-Oberfläche
        wizard.py                   Einrichtungsassistent (Willkommen/Einrichtung/
                                     Systemtest/Modell/Eingabeordner)
        main_window.py              Hauptfenster
        worker.py                   QThread-Hintergrundverarbeitung
        dialogs.py                  Systemprompt-Editor, Systemdiagnose
        theme.py                    Einheitliches, modernes Erscheinungsbild
        strings.py                  Gemeinsame Textbausteine
    services\                       Kernlogik (ohne Qt-Abhängigkeit)
        environment_service.py      GPU-Erkennung, Torch-Index-Auswahl, pip-Befehle
        chunking_service.py         Zehn-Minuten-Chunk-Planung
        manifest_service.py         Arbeitsordner/Manifest, Fortsetzbarkeit
        ffmpeg_service.py           FFmpeg/ffprobe-Suche, -Download, Normalisierung
        transcription_service.py    WhisperX-Python-API
        diarization_service.py      pyannote (In-Memory-Waveform)
        merge_service.py            Globale Zeitstempel, Overlap-Dedup
        speaker_merge_service.py    Sprecherzuordnung über Chunk-Grenzen
        model_service.py            Modell-/Cache-/Geräteverwaltung
        model_download_service.py   Einmaliger Modell-Download (GUI + Konsole)
        ollama_service.py           Lokaler Ollama-Client + Installer-Download
        protocol_service.py         Mehrstufige Protokollauswertung
        export_service.py           TXT/JSON/SRT/VTT/Protokoll/Bericht
        pipeline_service.py         Orchestrierung des Gesamtablaufs
    utils\
        paths.py                    Ausschließlich relative Pfade (portabel)
        app_config.py                Lokale, rechnerspezifische Konfiguration
        timeformat.py, logging_setup.py, hf_env.py, json_validation.py
        diagnostics.py              Systemdiagnose (GUI + Skripte)
        pyannote_patch.py           Separates Prüf-/Reparaturskript (Logik)
        setup_status.py             Einrichtungsstatus.json-Verwaltung (manueller Weg)
    einstellungen\
        systemprompt_protokoll.txt          bearbeitbarer Systemprompt
        systemprompt_protokoll.default.txt  unveränderliche Referenzkopie
        fachbegriffe.txt                    (optional, vom Nutzer angelegt)
    logs\                           Logdatei (keine Tokens/Audioinhalte)
    tools\ffmpeg\                   optionaler manueller ODER automatisch
                                     heruntergeladener FFmpeg-Ordner
    runtime\venv\                   automatisch angelegte private Python-Umgebung
                                     (entsteht erst beim ersten Start, nicht im ZIP)
    tests\                          automatisierte Tests (pytest)
    arbeitsdaten\                   Chunks/Zwischenstände je Quelldatei (Hash)
    ausgabe\                        Standard-Ausgabeordner
    konfiguration.json              zuletzt genutzte Ordner/Geräteauswahl (entsteht
                                     erst beim ersten Start, nicht im ZIP)

    Start-Protokoll-Assistent.ps1   Einfachster Start auf JEDEM PC (empfohlen)
    _env_helper.ps1                 Gemeinsame Hilfsfunktion für die übrigen .ps1-Skripte

    Einrichtung-Lokal.ps1           Fortgeschrittener Weg: gefuehrte 5-Phasen-Einrichtung
    Anwendung-starten.ps1           Fortgeschrittener Weg: Start nur nach vollständiger Einrichtung
    Systempruefung.py               Phase 1 + Phase 4 (Systemcheck/Offline-Check)
    Modelle-herunterladen.py        Phase 3 (WhisperX/Alignment/pyannote/Ollama)
    Einrichtungsstatus.json         wird von 'Einrichtung-Lokal.ps1' erzeugt (kein Bestandteil des ZIP)

    setup_lokal.ps1                 Nur Python-Umgebung, setzt vorhandene '.venv-whisperx' voraus
    start_lokal.ps1                 Direkter Start ohne Status-Prüfung (Entwicklung)
    check_pyannote_fix.ps1          Nur die pyannote-Korrektur prüfen/anwenden
    build_windows.ps1               PyInstaller-Build (One-Directory)
    protokoll_assistent_lokal.spec  PyInstaller-Spezifikation
    requirements-local-gui.txt      Zusatzpakete für den manuellen '.venv-whisperx'-Weg
```

---

## Installation — Schritt für Schritt

1. **ZIP entpacken** nach `protokoll-assistent\lokale_windows_app` (oder an
   einen beliebigen anderen Ort — die Anwendung ermittelt alle Pfade
   relativ zu sich selbst).
2. PowerShell in diesem Ordner öffnen und starten:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\Start-Protokoll-Assistent.ps1
   ```
3. **Einrichtung abwarten**: Beim allerersten Start richtet sich die
   Anwendung automatisch ein (private Python-Umgebung, PyTorch passend zu
   GPU/CPU, WhisperX, pyannote.audio, PySide6). Ein Fortschrittsfenster
   zeigt den Verlauf.
4. Im sich öffnenden **Einrichtungsassistenten**: FFmpeg/Ollama werden bei
   Bedarf automatisch heruntergeladen, danach die KI-Modelle. Fehlt ein
   Hugging-Face-Token, werden Sie einmalig **verdeckt** danach gefragt
   (wird nicht gespeichert).
5. **Systemtest abwarten** — zeigt, ob alles einsatzbereit ist.
6. **Eingabeordner auswählen** — den Ordner mit Ihren Aufnahmen wählen;
   unterstützte Dateien werden aufgelistet.
7. Das **Hauptfenster** öffnet sich. Eine Datei aus der Liste auswählen
   (oder „Andere Datei wählen …") und **Verarbeitung starten**.
8. **Lange Aufnahme auswählen** (Audio oder Video) — Transkription,
   Sprechertrennung und Protokollerstellung laufen automatisch nacheinander.
9. Bei **Unterbrechung** (Programm/Rechner beendet) die Anwendung erneut
   starten, denselben Ordner/dieselbe Datei wählen und in der Oberfläche
   **„Verarbeitung fortsetzen"** wählen — bereits abgeschlossene Chunks
   werden nicht erneut berechnet.
10. Spätere Starts: einfach wieder `Start-Protokoll-Assistent.ps1`
    ausführen — die Einrichtung läuft dann sofort durch (nur der schnelle
    Systemtest), ohne erneuten Download.

---

## Bedienung der Anwendung

- **Eingabeordner**: einmal gewählt, werden unterstützte Dateien (mp3, mp4,
  m4a, wav, aac, flac, ogg, opus, mov, mkv, webm) darin aufgelistet;
  einfach anklicken. „Ordner wechseln …" wählt einen anderen Ordner,
  „Andere Datei wählen …" öffnet bei Bedarf einen klassischen Dateidialog.
- **Ausgabeordner**: Standard ist `ausgabe\` neben der Anwendung, änderbar
  und wird gemerkt.
- **Sprache**: Deutsch (Standard) oder automatische Erkennung.
- **Sprechertrennung aktivieren**: standardmäßig aktiviert. Deaktiviert
  überspringt die pyannote-Diarisierung komplett (schnellere Verarbeitung)
  und liefert ein anonymes Transkript ganz ohne Sprecherzuordnung — sinnvoll,
  wenn nur der Inhalt zählen und die Aussagen anonym bleiben sollen. Die
  Sprecherzahl-Begrenzung und die Sprechertabelle sind in diesem Fall
  ebenfalls deaktiviert, da es keine Sprecher gibt.
- **Sprecherzahl**: automatisch (Standard) oder manuell mit Min./Max.
  (nur bei aktivierter Sprechertrennung).
- **Offline-Modus**: standardmäßig aktiviert.
- **Lokales Protokoll erstellen (Ollama)**: standardmäßig aktiviert.
- **Systemprompt bearbeiten**: öffnet `einstellungen\systemprompt_protokoll.txt`
  zur Bearbeitung, mit Reset-Funktion auf den mitgelieferten Standard.
- **Systemdiagnose**: prüft Python, PyTorch, CUDA/GPU (informativ — CPU
  funktioniert auch), FFmpeg, WhisperX-/pyannote-Import, Modell-Cache,
  HF_TOKEN (nur Ja/Nein), Ollama, Schreibzugriff.
- **Start/Abbrechen**: Verarbeitung läuft in einem Hintergrund-Thread, die
  Oberfläche friert nicht ein. Abbruch wirkt nach dem aktuellen Chunk.
- **Fortschrittsanzeige**: aktueller Chunk, Gesamtfortschritt, Laufzeit,
  geschätzte Restdauer, Status für Transkription und Ollama-Auswertung getrennt.
- **Sprechertabelle**: technische ID, Segmentanzahl, Sprechdauer, editierbarer
  Name. „Namen übernehmen & Ausgaben neu erzeugen" erstellt TXT/JSON/SRT/VTT
  **ohne erneute Transkription** neu.

---

## Ausgabedateien

Je Verarbeitungslauf (eindeutiger Zeitstempel im Dateinamen, kein
unbeabsichtigtes Überschreiben vorhandener Ergebnisse):

- `<Datei>_lokal_transkript_<Zeitstempel>.txt` — Volltranskript
- `<Datei>_lokal_transkript_<Zeitstempel>.json` — strukturiertes Transkript
  (Quelldatei, Modell, Sprache, Gerät, Dauer, Sprecherzuordnung, Segmente,
  Gesamttext)
- `<Datei>_lokal_transkript_<Zeitstempel>.srt` / `.vtt`
- `<Datei>_protokoll_<Zeitstempel>.json` / `.md` — finales Protokoll
  (sofern Ollama-Auswertung aktiviert)
- `arbeitsdaten\<Hash>\zusammengefuehrt\verarbeitungsbericht.json` / `.md` —
  Chunk-Status, verwendete Modelle, Laufzeiten

TXT-Format-Beispiel:

```text
PROTOKOLL-ASSISTENT – LOKALES VOLLTRANSKRIPT MIT SPRECHERTRENNUNG
Quelldatei: dbb_TEST_10_Minuten.mp3
Erstellt: 2026-01-01T10:00:00+01:00
Transkriptionsmodell: WhisperX large-v3-turbo
Verarbeitung: vollständig lokal
Erkannte Sprache: de
Erkannte Sprecher: 5

[00:00:02.780 --> 00:00:17.180] Sprecher 1: Text
[00:00:35.300 --> 00:00:37.160] Sprecher 2: Text
```

---

## Verfügbare Whisper-Modelle

Im Einrichtungsassistenten (Schritt "Modell") und jederzeit im Hauptfenster
(Dropdown "Whisper-Modell") stehen folgende Modelle zur Auswahl, absteigend
nach Anspruch sortiert:

| Modell-ID | Beschreibung | Empfohlen ab |
|---|---|---|
| `large-v3` | Beste Qualität, am langsamsten. Höchste Genauigkeit, auch bei Akzenten/Dialekten/Fachbegriffen. | ≥ 10 GB VRAM |
| `large-v3-turbo` | **Empfohlener Standard.** Fast so genau wie Large v3, aber deutlich schneller und genügsamer. | ≥ 6 GB VRAM |
| `distil-large-v3` | Sehr schnell und genügsam; primär für Englisch destilliert — für deutsche Aufnahmen ggf. spürbar ungenauer als Large v3(-Turbo). | ≥ 6 GB VRAM |
| `medium` | Guter Kompromiss, solide mehrsprachige Qualität, läuft auch auf kleineren GPUs. | ≥ 5 GB VRAM |
| `small` | Deutlich schneller, spürbar weniger genau. Auch für CPU-Betrieb geeignet. | ≥ 2 GB VRAM |
| `base` | Sehr genügsam, nur für einfache Aufnahmen oder sehr schwache Hardware. | ≥ 1 GB VRAM |
| `tiny` | Minimal, nur zum Ausprobieren, nicht für echte Protokolle empfohlen. | überall |

**Empfehlung ohne erkannte GPU (reiner CPU-Betrieb):** `small` bei ≥ 16 GB
Arbeitsspeicher, sonst `base`.

Diese Liste ist eine kuratierte Auswahl bewährter Modelle, keine
abschließende Einschränkung: Über "Eigene Modell-ID eingeben …" (im
Einrichtungsassistenten) lässt sich jede andere gültige WhisperX-/
CTranslate2-Modell-ID verwenden (z. B. eine eigene Hugging-Face-Repo-ID).

Die Empfehlung ist eine transparente, rein hardwarebasierte Heuristik
(``services/model_service.py::empfehle_whisper_modell``) — sie entscheidet
nichts automatisch endgültig, sondern schlägt nur vor; die Auswahl trifft
immer der Nutzer. Die getroffene Wahl wird in `konfiguration.json`
gespeichert (Schlüssel `whisper_modell`) und bei jedem weiteren Start
vorausgewählt, bis sie bewusst geändert wird.

---

## Langzeitaufnahmen (Chunking, Fortsetzen)

Aufnahmen über 10 Minuten werden automatisch in **600-Sekunden-Chunks mit
10 Sekunden Überlappung** zerlegt und **ausschließlich sequenziell**
verarbeitet (niemals mehrere Chunks gleichzeitig). Für jede Quelldatei
entsteht ein eigener Arbeitsordner `arbeitsdaten\<SHA-256-Hash der Datei>\`
mit `manifest.json`, den einzelnen Chunk-Audios/-Transkripten und den
zusammengeführten Ergebnissen.

- **Globale Zeitstempel**: Alle Ausgaben beziehen sich auf die
  Originalaufnahme, nicht auf den einzelnen Chunk.
- **Overlap-Dedup**: Im 10-Sekunden-Überlappungsbereich werden eindeutige
  Textdubletten entfernt; mehrdeutige Passagen bleiben erhalten und werden
  als `moegliche_ueberschneidung` markiert.
- **Sprecherzuordnung über Chunk-Grenzen**: Die Diarisierung läuft bevorzugt
  **einmal global** auf dem normalisierten Gesamtaudio; die Sprecher-IDs
  werden den Segmenten anhand der globalen Zeitstempel zugeordnet
  (`services/speaker_merge_service.py::assign_speakers_by_overlap`).
  Dadurch bleiben IDs auch über lange Pausen hinweg stabil. Für den Fall,
  dass eine globale Diarisierung nicht möglich ist, steht zusätzlich eine
  Embedding-basierte Zuordnung über Chunk-Grenzen mit konservativem
  Schwellwert bereit (`match_speakers_across_chunks`) — sie führt Sprecher
  **niemals** unterhalb des Schwellwerts willkürlich zusammen, sondern legt
  dann einen neuen Sprecher an.
- **Fortsetzbar**: Bereits abgeschlossene Chunks werden bei einem erneuten
  Lauf nicht neu berechnet. Der zuletzt fehlgeschlagene Chunk wird erkannt
  und erneut versucht. In der Oberfläche stehen dafür „Verarbeitung
  fortsetzen", „Neu beginnen" und „Zwischenstände öffnen" zur Verfügung.

---

## Lokale Protokollerstellung (Ollama)

Nach dem Zusammenführen aller Chunks wertet ein **lokales Ollama-Modell**
(`qwen3:8b`, `http://127.0.0.1:11434`, Temperatur 0, JSON-Ausgabe) das
Transkript **dreistufig** aus:

1. **Chunk-Analyse** — jeder Abschnitt einzeln, nur Aussagen aus diesem Abschnitt.
2. **Zwischenzusammenführung** — benachbarte Analysen gruppenweise konsolidiert
   (Standard: 4 pro Gruppe), Dopplungen aus Überlappungen entfernt.
3. **Gesamtprotokoll** — alle konsolidierten Analysen zum finalen,
   strukturierten Protokoll (JSON gemäß Systemprompt-Struktur) zusammengeführt.

Jede Stufe wird als Datei in `arbeitsdaten\<Hash>\analysen\` bzw.
`...\zusammengefuehrt\` gespeichert — bei einem Fehler beginnt die
Auswertung **nicht** komplett neu. Jede Modellantwort wird als JSON validiert;
bei ungültiger Antwort erfolgt **ein** gezielter Reparaturversuch, danach eine
verständliche Fehlermeldung (Rohantwort bleibt lokal gespeichert, gültige
vorherige Ergebnisse werden nicht überschrieben).

Der Systemprompt liegt editierbar in
`einstellungen\systemprompt_protokoll.txt` und kann in der Oberfläche vor
jeder Auswertung angesehen, geändert und zurückgesetzt werden.

---

## Windows-Build (EXE)

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

Erstellt einen **One-Directory-Build** (kein One-File, da WhisperX/PyTorch/CUDA
dafür ungeeignet groß sind) unter `dist\Protokoll-Assistent-Lokal\`. Startpunkt:
`Protokoll-Assistent-Lokal.exe`. Modelldateien werden **nicht** in den Build
kopiert — die EXE verwendet Ihren vorhandenen Hugging-Face-/Ollama-Cache. In
einer gebauten EXE ist `bootstrap.py` automatisch inaktiv (alles ist bereits
gebündelt) — der Einrichtungsassistent zeigt direkt Systemtest und
Eingabeordner-Auswahl.

**Wichtig:** Diese EXE konnte in der Entwicklungsumgebung dieses Auftrags
**nicht** mit echten Modellen getestet werden (kein Windows, keine
NVIDIA-GPU, WhisperX/pyannote nicht installierbar). Was tatsächlich geprüft
wurde: Die PyInstaller-Spezifikation wurde probeweise mit PySide6 (ohne
WhisperX/PyTorch) gebaut — der Build lief fehlerfrei durch, und die
resultierende Anwendung startete tatsächlich bis zur vollständigen
Oberfläche (Bootstrap wurde dabei korrekt als „bereits gebündelt"
übersprungen). Bitte auf Ihrem Rechner nach dem Build zusätzlich prüfen:

1. `dist\Protokoll-Assistent-Lokal\Protokoll-Assistent-Lokal.exe` startet und
   zeigt Einrichtungsassistent bzw. Datenschutzhinweis.
2. Systemdiagnose in der Oberfläche zeigt PyTorch/WhisperX/pyannote als „OK".
3. Ein-Minuten-Testdatei (`dbb_TEST_1_Minute.mp3`) läuft vollständig durch.
4. Zehn-Minuten-Testdatei (`dbb_TEST_10_Minuten.mp3`) läuft vollständig durch
   inkl. Chunking, Zusammenführung und Ollama-Protokoll.

Meldet PyInstaller `ModuleNotFoundError` für ein WhisperX-/pyannote-
Zusatzpaket, ergänzen Sie es in der Liste `PACKAGES_TO_COLLECT` am Anfang von
`protokoll_assistent_lokal.spec`.

---

## Fortgeschrittener/manueller Einrichtungsweg

Für die meisten Nutzer genügt `Start-Protokoll-Assistent.ps1` (siehe oben).
Für IT-Rollouts auf mehreren Rechnern oder wenn Sie die Einrichtung
unabhängig vom GUI-Assistenten nachvollziehbar protokollieren möchten,
steht zusätzlich der ursprüngliche, PowerShell-basierte 5-Phasen-Weg zur
Verfügung:

```powershell
powershell -ExecutionPolicy Bypass -File .\Einrichtung-Lokal.ps1
powershell -ExecutionPolicy Bypass -File .\Anwendung-starten.ps1
```

- **Phase 1** (`Systempruefung.py`): Windows, Python 3.10/3.11, NVIDIA-GPU/
  -Treiber, CUDA, RAM, Speicherplatz, FFmpeg/ffprobe, Ollama.
- **Phase 2** (`setup_lokal.ps1`): setzt eine bereits vorhandene
  `.venv-whisperx` voraus und installiert dort nur die GUI-/Build-Extras
  (`requirements-local-gui.txt`) sowie die pyannote-Korrektur.
- **Phase 3** (`Modelle-herunterladen.py`): WhisperX (Standard:
  `large-v3-turbo`, mit `--modell <id>` anpassbar -- siehe
  [Verfügbare Whisper-Modelle](#verfügbare-whisper-modelle)), Alignment,
  pyannote, `ollama pull qwen3:8b`.
- **Phase 4**: Offline-Funktionsprüfung (alles läuft ohne Internetzugriff).
- **Phase 5**: `Einrichtungsstatus.json` wird als vollständig markiert.
  `Anwendung-starten.ps1` verweigert den Start, solange eine Phase fehlt.

`check_pyannote_fix.ps1` prüft/korrigiert ausschließlich die
pyannote-NaN-Absicherung, unabhängig vom gewählten Weg.

### Welche Pakete beim ersten Start installiert werden

Die Listen stehen in zwei Textdateien, nicht im Code:

| Datei | Woher installiert |
|---|---|
| `requirements-torch.txt` | eigener Index von pytorch.org (CUDA oder CPU, je nach GPU) |
| `requirements-laufzeit.txt` | PyPI |

Das ist kein Schönheitsentscheid: Als Python-Liste waren ausgerechnet die
größten und sicherheitsrelevantesten Pakete des Projekts (PyTorch,
WhisperX, pyannote.audio) für Dependabot und `pip-audit` **unsichtbar** —
sie tauchten in keinem Manifest auf. Als Datei werden sie erfasst.

### Passen Aktualisierungen dieser Pakete zusammen?

Die Installation läuft in **zwei** pip-Aufrufen aus **zwei** Quellen, und
genau dazwischen liegt eine Falle: Der zweite Aufruf kann PyTorch wieder
überschreiben. Verlangt WhisperX etwa `torch~=2.8.0`, der eingestellte
CUDA-Index kennt aber nur 2.5.1, dann installiert pip beim zweiten Aufruf
kommentarlos ein PyTorch von PyPI — und der CUDA-Build ist weg. Auf dem
Rechner des Anwenders fällt das erst auf, wenn die GPU unerwartet nicht
benutzt wird.

Deshalb gibt es:

```powershell
uv run python lokale_windows_app/tools/laufzeit_pakete_pruefen.py
```

Das Skript installiert nichts und braucht keine GPU — es löst die Pakete
nur auf (wenige Sekunden) und prüft zweierlei:

1. Passen die Laufzeit-Pakete untereinander?
2. Gibt es die dabei geforderte PyTorch-Fassung auch in den beiden
   eingestellten pytorch.org-Indizes?

Derselbe Lauf steckt in der CI (Ablauf „Laufzeit-Pakete der lokalen
Anwendung"), damit ein Dependabot-Vorschlag auffällt, bevor er zusammen
mit dem CUDA-Index nicht mehr zusammenpasst.

---

## Tests

### Automatisiert (in dieser Umgebung bereits ausgeführt)

```powershell
& .\runtime\venv\Scripts\python.exe -m pytest lokale_windows_app\tests -v
```

165 Tests decken u.a. ab: die hardwarebasierte Whisper-Modellempfehlung
(VRAM-/RAM-Staffelung, CPU-Fallback, Diagnose-Auswertung), Chunk-Grenzen und
10-Sekunden-Überlappung
(inkl. des Beispiels aus dem Auftrag: Chunk 3 beginnt bei 00:19:40),
Umrechnung lokaler in globale Zeitstempel, Entfernung eindeutiger
Überlappungsdubletten bei Erhalt unsicherer Textstellen, Wiederaufnahme nach
simuliertem Abbruch, Erkennung bereits fertiger Chunks, Sprecherzuordnung
über Chunk-Grenzen (Cosinus-Ähnlichkeit, konservativer Schwellwert, niemals
willkürliche Zusammenführung), JSON-Validierung von Ollama-Antworten,
dreistufige Ollama-Auswertung mit Resumability und Reparaturversuch,
Verhalten bei einem fehlerhaften einzelnen Chunk, TXT/SRT/VTT/JSON-Export,
FFmpeg-Suchreihenfolge und -Download, Ollama-Installer-Download, die
selbstinstallierende Laufzeitumgebung (`bootstrap.py`: Legacy-Venv-Erkennung,
Neuanlage, GPU/CPU-Torch-Auswahl, Python-Versionsprüfung, Fehlerbehandlung),
die portable Pfad-/Konfigurationslogik, die pyannote-Korrektur (Idempotenz,
Backup, Syntaxprüfung) sowie Diagnosefunktionen. Es wurden ausschließlich
künstlich erzeugte Testdaten verwendet — **keine echten Sprachaufnahmen**.

### Nur auf Ihrem Rechner möglich (GPU/Audio-abhängig)

1. `dbb_TEST_1_Minute.mp3` über die Oberfläche auswählen und verarbeiten.
   Erwartung gemäß Ihren bisherigen Tests: zwei Sprecher korrekt erkannt,
   Sprecherwechsel korrekt, GPU-Verarbeitung erfolgreich.
2. `dbb_TEST_10_Minuten.mp3` verarbeiten. Erwartung: fünf plausible Sprecher,
   auch nach längeren Pausen stabile IDs (z.B. `SPEAKER_03`, `SPEAKER_04`).
3. Eine Aufnahme über 10 Minuten (z.B. 25–35 Minuten) verarbeiten, um Chunking,
   Zusammenführung und Ollama-Protokoll vollständig zu prüfen.
4. Verarbeitung einer langen Aufnahme bewusst per Task-Manager beenden und
   über „Verarbeitung fortsetzen" erneut starten.
5. Die Anwendung auf einem **zweiten, „frischen" PC ohne `.venv-whisperx`**
   ausprobieren, um den automatischen Einrichtungsweg (`runtime\venv`,
   FFmpeg-/Ollama-Download) zu prüfen.

---

## Fehlerbehandlung / Problembehebung

| Situation | Verhalten |
|---|---|
| Keine Datei ausgewählt | Verständliche Meldung, kein Start |
| Datei nicht gefunden / leer | Verständliche Meldung, kein Start |
| Nicht unterstütztes Format | Meldung mit unterstützten Endungen |
| FFmpeg nicht gefunden | Wird automatisch heruntergeladen; sonst Meldung |
| Kein Python 3.10/3.11 gefunden | Klare Meldung mit Download-Link, kein Absturz |
| CUDA nicht verfügbar | Kein Fehler — Verarbeitung läuft auf der CPU weiter |
| GPU-Speicher reicht nicht | Fehlermeldung aus WhisperX/pyannote, keine Rohdaten geloggt |
| Modell fehlt im Offline-Modus | Meldung; einmaliger Download nur nach bewusster Freigabe |
| HF_TOKEN fehlt bei Download | Verdeckte Abfrage, keine Speicherung |
| Ollama fehlt | Installer wird heruntergeladen und geöffnet, Nutzer schließt ihn ab |
| Ungültiger Ausgabeordner / Schreibfehler | Meldung vor Start, kein Datenverlust |
| Programmabbruch | Sicher über „Abbrechen" (wirkt nach aktuellem Chunk) |

Vollständige technische Details (niemals Tokens oder Audioinhalte) stehen in
`logs\protokoll_assistent_lokal.log`.

**TorchCodec/FFmpeg-9-Warnung**: Die Anwendung lädt Audio über
`whisperx.load_audio` (eigener FFmpeg-Subprozess) einmal in den Speicher und
übergibt pyannote ein Waveform-Dictionary (`{"waveform":..., "sample_rate":...}`),
sodass pyannote die Datei nicht selbst über TorchCodec öffnen muss.

**pyannote-NaN-Korrektur**: `check_pyannote_fix.ps1` prüft und korrigiert
die zugehörige `pooling.py` in der jeweils aktiven virtuellen Umgebung
(`.venv-whisperx` oder `runtime\venv`) nur bei eindeutigem Fund, legt vorher
ein Backup an und prüft danach mit `py_compile`. Die Anwendung selbst ruft
dieses Skript **nicht** automatisch bei jedem Start auf.

---

## Was hier bereits geprüft wurde und was Sie selbst prüfen müssen

**In dieser Entwicklungsumgebung geprüft** (Linux, ohne GPU, ohne
WhisperX/PyTorch/pyannote/Ollama vorinstalliert):

- Alle Python-Module kompilieren fehlerfrei (`py_compile`).
- 165 automatisierte pytest-Tests laufen grün (reine Logik: Chunking,
  Manifest/Resume, Merge/Dedup, Sprecherzuordnung, JSON-Validierung,
  Ollama-Client gegen simulierte Antworten, dreistufige Protokoll­pipeline,
  Export, FFmpeg-Such-/Download-Logik, Ollama-Installer-Download,
  selbstinstallierende Laufzeitumgebung, portable Pfad-/Konfigurations­logik,
  pyannote-Patch-Logik, Diagnosefunktionen, Pipeline-Orchestrierung inkl.
  Abbruch/Fortsetzen/fehlerhaftem Chunk, hardwarebasierte Whisper-
  Modellempfehlung — alle mit ausgetauschten Backends, ohne echte
  ML-Modelle oder echte Downloads).
- Der neue Einrichtungsschritt "Modell" (`gui/wizard.py::ModelChoicePage`)
  sowie die Modellauswahl im Hauptfenster wurden in einer Offscreen-Qt-
  Umgebung tatsächlich konstruiert und durchgeklickt: Vorauswahl anhand
  simulierter Diagnoseergebnisse, Umschalten auf "Eigene Modell-ID
  eingeben …", simulierter Download inkl. Freischaltung von "Weiter", sowie
  Speichern/Wiederherstellen der Wahl in `konfiguration.json`.
- Die komplette PySide6-Oberfläche (Einrichtungsassistent mit allen vier
  Seiten, Hauptfenster mit Eingabeordner-Auswahl, Systemprompt-Dialog,
  Systemdiagnose) wurde in einer Offscreen-Qt-Umgebung tatsächlich
  konstruiert und durchgeklickt (kein reiner Code-Review) — inklusive des
  Uebergangs vom Assistenten zum Hauptfenster mit vorausgewähltem Ordner.
- `bootstrap.py` wurde mit vollständig simulierten (keine echten Downloads/
  Installationen) venv-/pip-/Python-Versions-Szenarien getestet: bereits
  vorhandene `.venv-whisperx` wird direkt verwendet, ein „frischer PC" legt
  `runtime\venv` an und installiert GPU- bzw. CPU-Pakete passend, eine
  gebaute EXE überspringt den Bootstrap vollständig, ein fehlgeschlagener
  Installationsschritt bricht sauber ab statt weiterzumachen.
- Die PyInstaller-Spezifikation wurde probeweise gebaut (mit PySide6, ohne
  WhisperX/PyTorch) und die daraus gebaute Anwendung startete fehlerfrei bis
  zur Oberfläche, mit korrekt übersprungenem Bootstrap.

**Nur auf einem echten Windows-Rechner testbar** (nicht behauptet, hier
getestet worden zu sein):

- Der tatsächliche automatische Download/Installation von PyTorch (GPU- oder
  CPU-Variante), WhisperX, pyannote.audio auf einem wirklich neuen PC ohne
  vorbereitete Umgebung.
- Tatsächliche WhisperX-Transkription, pyannote-Diarisierung und
  Ollama-Protokollerstellung mit echten Audiodateien.
- Der automatische FFmpeg- und Ollama-Installer-Download.
- Die gebaute `.exe` selbst (PyInstaller-Bündelung von WhisperX/PyTorch/CUDA).
- Alle PowerShell-Skripte (`Start-Protokoll-Assistent.ps1`,
  `Einrichtung-Lokal.ps1`, `Anwendung-starten.ps1`, `setup_lokal.ps1`,
  `start_lokal.ps1`, `check_pyannote_fix.ps1`, `build_windows.ps1`) —
  PowerShell ist auf dieser Linux-Umgebung nicht verfügbar.
- Verhalten bei tatsächlich mehrstündigen Aufnahmen, echtem GPU-Speicherdruck
  und der realen pyannote-Kompatibilitätskorrektur an Ihrer installierten
  Version.
