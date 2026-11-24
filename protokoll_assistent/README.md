# VERMERK Desktop — technische Referenz

> Die Kurzanleitung (Installation, Bedienung, Einstellungen) steht in der
> [README im Projektstamm](../README.md). Diese Datei geht in die Tiefe:
> Grafikkarten, Whisper-Modelle, Chunking, Ollama, Fehlerbehebung.

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

1. **Anwendung starten** (Startmenü bzw. `VERMERK.exe`; aus dem Quelltext
   siehe [README im Projektstamm](../README.md#starten)). Das Fenster startet
   den Dienst (`python -m protokoll_assistent.api`) und zeigt die
   **Ersteinrichtung** (Seiten der Oberfläche, Endpunkte in
   `api/routen_einrichtung.py`). Bis zur Zustimmung wird **nichts**
   heruntergeladen:
   - **Willkommen** — was das Programm macht, in vier Schritten.
   - **Ihr Computer** — Arbeitsspeicher, Prozessor, Grafikkarte und freier
     Platz; je Arbeitsschritt (Mitschrift, Sprechererkennung, Protokoll, Frag
     mein Meeting), ob er hier gut, langsam oder nicht sinnvoll läuft und wie
     lange eine Stunde Aufnahme ungefähr dauert, dazu eine Empfehlung.
   - **Arbeitsweise** — alles auf diesem Computer, alles online oder je
     Schritt gemischt. Online wird nie vorausgewählt.
   - **Was dafür nötig ist** — jeder Baustein mit Download- und Platzbedarf,
     Vorhandenes ist markiert; Lizenzhinweise; Zustimmung per Häkchen.
   - **Einrichtung** — FFmpeg, Ollama (offizieller Installer, Signatur
     geprüft, still für das eigene Benutzerkonto installiert) und die
     Sprachmodelle. Fehlt für die lokale Mitschrift noch die Rechenumgebung,
     startet der Dienst dafür einmal neu: Er legt eine eigene, private
     Umgebung an (`runtime\venv`) und installiert dort PyTorch passend zur
     erkannten Grafikkarte (oder für reinen CPU-Betrieb), faster-whisper,
     pyannote.audio usw. — mit kleinem Fortschrittsfenster, je nach
     Internetverbindung einige Minuten. Danach geht die Einrichtung weiter.
   - **Mitschrift** — Whisper-Modell (vorgeschlagen nach der Analyse, siehe
     [Verfügbare Whisper-Modelle](#verfügbare-whisper-modelle)) und der
     Hugging-Face-Zugang für die Sprechererkennung, mit Anleitung; auf Wunsch
     verschlüsselt in der Windows-Anmeldeinformationsverwaltung gemerkt.
   - **Fertig** — Übersicht; wer online arbeiten will, trägt hier Anbieter
     und Schlüssel ein.

   „Später einrichten“ schließt den Dialog; beim nächsten Start erscheint er
   wieder. Mit „Nicht mehr fragen“ bleibt er weg — dann lädt die Anwendung
   auch die Rechenumgebung nicht von selbst, bis Sie unter Einstellungen →
   Transkription → Lokal „Einrichtung starten“ wählen.
2. Danach können Sie in der **Oberfläche** direkt eine Datei auswählen oder
   aufnehmen und die Verarbeitung starten. Das Whisper-Modell lässt sich dort
   jederzeit über das Dropdown "Whisper-Modell" ändern, die Wahl wird gemerkt.

Der zuletzt verwendete Eingabe-/Ausgabeordner wird lokal in
`konfiguration.json` gemerkt (keine Zugangsdaten, keine Rechnernamen) —
beim nächsten Start ist er bereits vorausgewählt.

---

## Voraussetzungen

Einzige echte Voraussetzung auf einem **neuen** PC:

- Windows, mit **Python 3.10 oder 3.11** installiert
  (<https://www.python.org/downloads/> — beim Installieren „Add python.exe
  to PATH" aktivieren).

Alles Weitere (FFmpeg, PyTorch, faster-whisper, pyannote.audio, Ollama
inkl. Modell) wird von der Anwendung selbst automatisch eingerichtet, wie
oben beschrieben. Für gute Geschwindigkeit wird eine NVIDIA-GPU mit
aktuellem Treiber empfohlen (erfolgreich getestet z.B. mit RTX 3060 Ti,
CUDA 12.8) — **zwingend** ist das aber nicht: ohne nutzbare GPU verarbeitet
die Anwendung auf der CPU weiter (deutlich langsamer, aber funktionsfähig).

### Welche Grafikkarten beschleunigen?

| Karte | Transkription | Sprechererkennung | Protokoll, „Frag mein Meeting“ (Ollama) | Woher PyTorch kommt |
|---|---|---|---|---|
| NVIDIA bis Ada/Hopper (Rechenfähigkeit < 12.0) | Grafikkarte | Grafikkarte | Grafikkarte | Index `cu126` |
| NVIDIA Blackwell (RTX 50xx, RTX PRO, Rechenfähigkeit ≥ 12.0) | Grafikkarte | Grafikkarte | Grafikkarte | Index `cu128` |
| AMD RX 7000/9000, PRO W7000, Radeon 880M/890M, 8040S–8060S | Grafikkarte (ROCm) | CPU | Grafikkarte (ROCm) | Index `cpu` |
| AMD RX 6800–6950 | CPU | CPU | Grafikkarte (ROCm) | Index `cpu` |
| andere AMD-Karten, Intel Arc, Radeon 680M/780M, Intel-Arc-Prozessorgrafik | CPU | CPU | Grafikkarte (Vulkan) | Index `cpu` |
| Intel UHD/Iris Xe, keine Grafikkarte | CPU | CPU | CPU | Index `cpu` |

Mindestens 3 GB Grafikspeicher; bei AMD-Prozessorgrafik zählt der im BIOS fest
zugewiesene. Die Liste und woher sie stammt: `services/grafikkarten_liste.py`.

Die Anwendung fragt die Rechenfähigkeit beim Treiber ab (`nvidia-smi`) und
wählt den passenden Index selbst. Das ist nötig, weil **kein einziger
CUDA-Index alle Karten bedient**: Blackwell-Kernel (`sm_120`) gibt es erst
ab CUDA 12.8, ältere Karten fallen in den neuen Indizes dagegen weg.

Beide Indizes sind **CUDA 12** — das ist Pflicht, kein Zufall: CTranslate2
(über faster-whisper der Kern der Transkription) lädt `cublas64_12.dll`.
Mit einem CUDA-13-Build läuft die Installation sauber durch, und erst die
erste Transkription bricht ab mit „Library cublas64_12.dll is not found or
cannot be loaded".

**AMD-Grafikkarten beschleunigen die Transkription seit 0.5.0-rc3.**
CTranslate2 (der Kern von faster-whisper) gibt es seit 4.7 auch für ROCm
unter Windows – allerdings nicht auf PyPI, sondern als Archiv auf seiner
Release-Seite. Auf einer passenden Karte holt die Einrichtung dieses Archiv
und AMDs ROCm-Bibliotheken (`repo.radeon.com`), beide mit fester Prüfsumme
(`services/rocm_laufzeit_service.py`). PyTorch bleibt der CPU-Build: PyTorch
mit ROCm gibt es für Windows nur als Vorschau für Python 3.12, deshalb
rechnet die Sprechererkennung auf AMD-Rechnern auf der CPU. Gemessen auf
einer RX 9070 XT: large-v3-turbo in 17- bis 27-facher Echtzeit, 79 Minuten
Aufnahme in 4 Minuten. Mit einem zu alten Grafiktreiber (ROCm 7.2.1 verlangt
26.2.2 oder neuer) findet CTranslate2 keine Karte, und die Transkription
läuft wie bisher auf der CPU.

Ob die GPU wirklich rechnen kann, wird **nicht** allein an
`torch.cuda.is_available()` festgemacht: Passt der CUDA-Build nicht zur
Kartengeneration, meldet das fälschlich `True`, und erst die erste echte
Rechnung scheitert — mitten in der Transkription. Die Anwendung rechnet
deshalb einmal kurz zur Probe und wechselt sonst sauber auf die CPU.

Für die lokale Protokollerstellung zusätzlich empfohlen: [Ollama](https://ollama.com)
mit dem Modell `qwen3.5:4b-q4_K_M` — wird ebenfalls automatisch heruntergeladen bzw.
der Installer angeboten, falls Ollama fehlt.

**Referenzrechner mit bereits vorhandener `.venv-whisperx`:** Wurde auf
diesem PC bereits manuell eine virtuelle Umgebung mit WhisperX 3.8.6,
PyTorch 2.8.0+cu128, CUDA 12.8 und pyannote.audio eingerichtet (so hiess
die Umgebung, als die Anwendung noch WhisperX benutzte) und liegt sie
NEBEN dem Anwendungsordner, erkennt die Anwendung dies automatisch und
verwendet sie direkt weiter (kein erneuter Download):

```text
protokoll-assistent\
    .venv-whisperx\
    protokoll_assistent_v2.py          (OpenRouter-Version — unverändert)
    protokoll_assistent\                (dieses Paket)
        bootstrap.py
        ...
```

Auf jedem anderen PC ohne diese Struktur legt die Anwendung stattdessen
automatisch `protokoll_assistent\runtime\venv` an — der Speicherort spielt
für die Bedienung keine Rolle.

---

## Ordnerstruktur

```text
protokoll_assistent\
    api\                            Der Dienst hinter dem Fenster (FastAPI):
                                     python -m protokoll_assistent.api
    ablauf\                         Steuerung ohne Oberfläche, Auftragswarteschlange
    bootstrap.py                    Selbstinstallierende Laufzeitumgebung (startet
                                     den Dienst darin neu)
    server\                         Servermodus (Eingangsordner, Container)
    services\                       Kernlogik (ohne Oberfläche)
        environment_service.py      GPU-Erkennung, Torch-Index-Auswahl, pip-Befehle
        chunking_service.py         Zehn-Minuten-Chunk-Planung
        manifest_service.py         Arbeitsordner/Manifest, Fortsetzbarkeit
        ffmpeg_service.py           FFmpeg/ffprobe-Suche, -Download, Normalisierung
        transcription_service.py    faster-whisper-Python-API
        diarization_service.py      pyannote (In-Memory-Waveform)
        merge_service.py            Globale Zeitstempel, Overlap-Dedup
        speaker_merge_service.py    Sprecherzuordnung über Chunk-Grenzen
        model_service.py            Modell-/Cache-/Geräteverwaltung
        model_download_service.py   Einmaliger Modell-Download (Konsole)
        ollama_service.py           Lokaler Ollama-Client + Installer-Download
        protocol_service.py         Mehrstufige Protokollauswertung
        export_service.py           TXT/JSON/SRT/VTT/Protokoll/Bericht
        pipeline_service.py         Orchestrierung des Gesamtablaufs
    utils\
        paths.py                    Ausschließlich relative Pfade (portabel)
        app_config.py                Lokale, rechnerspezifische Konfiguration
        timeformat.py, logging_setup.py, hf_env.py, json_validation.py
        diagnostics.py              Systemdiagnose (Dienst + Skripte)
        pyannote_patch.py           Separates Prüf-/Reparaturskript (Logik)
        setup_status.py             Einrichtungsstatus.json-Verwaltung (manueller Weg)
    einstellungen\
        systemprompt_protokoll.txt          bearbeitbarer Systemprompt
        systemprompt_protokoll.default.txt  unveränderliche Referenzkopie
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

    _env_helper.ps1                 Gemeinsame Hilfsfunktion für die übrigen .ps1-Skripte

    Einrichtung-Lokal.ps1           Fortgeschrittener Weg: gefuehrte 5-Phasen-Einrichtung
    systempruefung.py               Phase 1 + Phase 4 (Systemcheck/Offline-Check)
    modelle_herunterladen.py        Phase 3 (Whisper-Modell/pyannote/Ollama)
    Einrichtungsstatus.json         wird von 'Einrichtung-Lokal.ps1' erzeugt (kein Bestandteil des ZIP)

    setup_lokal.ps1                 Nur Python-Umgebung, setzt vorhandene '.venv-whisperx' voraus
    check_pyannote_fix.ps1          Nur die pyannote-Korrektur prüfen/anwenden
    requirements-anwendung.txt      Pakete der Anwendung (reichen für den API-Modus)
```

---

## Installation — Schritt für Schritt

1. **Installer ausführen** (`VERMERK-Desktop-Setup-<Version>.exe`, siehe
   [README im Projektstamm](../README.md)). Aus dem Quelltext startet man
   stattdessen das Fenster mit `VERMERK_PYTHON` (siehe dort, Abschnitt
   „Starten“).
2. **VERMERK starten** (Startmenü bzw. `VERMERK.exe`). Das Fenster startet
   den Dienst und zeigt die **Ersteinrichtung**.
3. **Einrichtung abwarten**: Wird die lokale Mitschrift gewählt, richtet sich
   der Dienst nach Ihrer Zustimmung beim nächsten Start automatisch ein
   (private Python-Umgebung, PyTorch passend zu GPU/CPU, faster-whisper,
   pyannote.audio). Ein kleines Fortschrittsfenster zeigt den Verlauf.
4. In der **Ersteinrichtung**: FFmpeg/Ollama werden bei Bedarf
   heruntergeladen, danach die KI-Modelle. Der Hugging-Face-Zugang für die
   Sprechererkennung wird dort eingetragen (auf Wunsch in der
   Windows-Anmeldeinformationsverwaltung gemerkt, nie als Datei).
5. Danach in der **Oberfläche** eine Aufnahme wählen (oder aufnehmen) und
   die Verarbeitung starten.
6. **Lange Aufnahme auswählen** (Audio oder Video) — Transkription,
   Sprechertrennung und Protokollerstellung laufen automatisch nacheinander.
7. Bei **Unterbrechung** (Programm/Rechner beendet) die Anwendung erneut
   starten, denselben Ordner/dieselbe Datei wählen und in der Oberfläche
   **„Verarbeitung fortsetzen"** wählen — bereits abgeschlossene Chunks
   werden nicht erneut berechnet.
8. Spätere Starts: einfach wieder VERMERK starten — die vorhandene
   Rechenumgebung wird ohne erneuten Download benutzt.

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
  funktioniert auch), FFmpeg, faster-whisper-/pyannote-Import, Modell-Cache,
  HF_TOKEN (nur Ja/Nein), Ollama, Schreibzugriff.
- **Start/Abbrechen**: Verarbeitung läuft als Auftrag in der Warteschlange
  des Dienstes, die Oberfläche friert nicht ein. Abbruch wirkt nach dem
  aktuellen Chunk.
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
VERMERK DESKTOP – LOKALES VOLLTRANSKRIPT MIT SPRECHERTRENNUNG
Quelldatei: dbb_TEST_10_Minuten.mp3
Erstellt: 2026-01-01T10:00:00+01:00
Transkriptionsmodell: large-v3-turbo (faster-whisper)
Verarbeitung: vollständig lokal
Erkannte Sprache: de
Erkannte Sprecher: 5

[00:00:02.780 --> 00:00:17.180] Sprecher 1: Text
[00:00:35.300 --> 00:00:37.160] Sprecher 2: Text
```

---

## Verfügbare Whisper-Modelle

In der Ersteinrichtung (Schritt „Mitschrift“) und in den Einstellungen
stehen folgende Modelle zur Auswahl, absteigend nach Anspruch sortiert:

| Modell-ID | Beschreibung | Braucht (gemessen) |
|---|---|---|
| `large-v3` | Beste Qualität, am langsamsten. Für besonders schwieriges Material (starke Dialekte, viele Fachbegriffe) bewusst wählbar. | 5,29 GB VRAM |
| `large-v3-turbo` | **Empfohlener Standard — immer.** Weicht nur 5,2 % von Large v3 ab, ist dabei rund siebenmal schneller. | 2,26 GB VRAM / 2,04 GB RAM |
| `distil-large-v3` | Primär für Englisch destilliert — für deutsche Aufnahmen ungeeignet. | ~2 GB VRAM |
| `medium` | **Nicht mehr empfohlen.** Gemessen schlechter als `small` (11,2 % statt 10,0 % Abweichung), dabei langsamer und speicherhungriger. | 2,29 GB VRAM |
| `small` | Genügsamer Rückfall, wenn der Speicher wirklich nicht reicht. Spürbar ungenauer (10,0 %). | 0,85 GB VRAM / 1,23 GB RAM |
| `base` | Für echte Protokolle unbrauchbar: jedes fünfte Wort weicht ab (20,9 %). | 0,35 GB VRAM |
| `tiny` | Nur zum Ausprobieren: fast jedes dritte Wort weicht ab (30,9 %). | 0,23 GB VRAM |

**Empfohlen wird immer `large-v3-turbo`** — auf jeder Grafikkarte und auch
ohne Grafikkarte. Das ist keine Vereinfachung, sondern gemessen (19.09.2026,
NVIDIA RTX PRO 500, echte deutsche Aufnahme von 10 Minuten, Abweichung
jeweils gegenüber `large-v3`):

* Turbo: **5,2 %** Abweichung, 2,26 GB, 26-fache Echtzeit auf der GPU
* Ohne Grafikkarte läuft Turbo mit **3,8-facher Echtzeit** bei 2,04 GB
  Arbeitsspeicher — der frühere Rückgriff auf kleinere Modelle im
  CPU-Betrieb ist damit hinfällig.

**Wenn der Speicher knapp ist**, wird trotzdem Turbo empfohlen und ein
Hinweis angezeigt, andere Programme zu schließen. Es wird **nicht** still
auf ein schwächeres Modell gewechselt: Wer Platz schafft, bekommt die volle
Qualität, und wer das nicht will, wählt selbst `small`.

Diese Liste ist eine kuratierte Auswahl bewährter Modelle, keine
abschließende Einschränkung: Über `konfiguration.json` (Schlüssel
`whisper_modell`) lässt sich jede andere gültige faster-whisper-/
CTranslate2-Modell-ID verwenden (z. B. eine eigene Hugging-Face-Repo-ID).

Die Empfehlung steht in ``services/model_service.py::empfehle_whisper_modell``,
der Speicherhinweis in ``speicherwarnung`` — sie entscheiden nichts
automatisch endgültig, sondern schlagen nur vor; die Auswahl trifft immer
der Nutzer. Die getroffene Wahl wird in `konfiguration.json`
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
(`qwen3.5:4b-q4_K_M`, `http://127.0.0.1:11434`, Temperatur 0, JSON-Ausgabe) das
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

Die Windows-Anwendung besteht aus zwei Builds, beide im Projektstamm:

```powershell
# Fenster (Tauri), bettet die gebaute Oberfläche ein
Push-Location oberflaeche; npm ci; npm run build; Pop-Location
Push-Location oberflaeche\src-tauri
cargo build --release --locked --features tauri/custom-protocol
Pop-Location
# Dienst (PyInstaller, One-Directory) und sein Rauchtest
uv run pyinstaller --noconfirm vermerk_dienst.spec
uv run python tools/dienst_rauchtest.py dist/vermerk-dienst/vermerk-dienst.exe
```

Der Dienst ist ein **One-Directory-Build** (`dist\vermerk-dienst\`) und enthält
bewusst **kein** PyTorch/faster-whisper/pyannote: Im lokalen Modus richtet
`bootstrap.py` diese Rechenumgebung mit dem vom Installer mitgelieferten
Python selbst ein und startet den Dienst darin aus dem Quelltext neu.
Modelldateien werden nie in den Build kopiert. Wie daraus der Installer
entsteht, steht in [`installer/README.md`](../installer/README.md); in der CI
baut `release.yml` alles zusammen.

---

## Fortgeschrittener/manueller Einrichtungsweg

Für die meisten Nutzer genügt der Installer mit der Ersteinrichtung (siehe
oben). Für IT-Rollouts auf mehreren Rechnern oder wenn Sie die Einrichtung
unabhängig von der Oberfläche nachvollziehbar protokollieren möchten,
steht zusätzlich der ursprüngliche, PowerShell-basierte 5-Phasen-Weg zur
Verfügung:

```powershell
powershell -ExecutionPolicy Bypass -File .\Einrichtung-Lokal.ps1
```

Gestartet wird danach wie gewohnt das Fenster; aus dem Quelltext mit
`VERMERK_PYTHON` auf die eingerichtete Umgebung (siehe
[README im Projektstamm](../README.md#starten)).

- **Phase 1** (`systempruefung.py`): Windows, Python 3.10/3.11, NVIDIA-GPU/
  -Treiber, CUDA, RAM, Speicherplatz, FFmpeg/ffprobe, Ollama.
- **Phase 2** (`setup_lokal.ps1`): setzt eine bereits vorhandene
  `.venv-whisperx` voraus und installiert dort nur die Pakete der Anwendung
  (`requirements-anwendung.txt`) sowie die pyannote-Korrektur.
- **Phase 3** (`modelle_herunterladen.py`): faster-whisper (Standard:
  `large-v3-turbo`, mit `--modell <id>` anpassbar -- siehe
  [Verfügbare Whisper-Modelle](#verfügbare-whisper-modelle)), Alignment,
  pyannote, `ollama pull qwen3.5:4b-q4_K_M`.
- **Phase 4**: Offline-Funktionsprüfung (alles läuft ohne Internetzugriff).
- **Phase 5**: `Einrichtungsstatus.json` wird als vollständig markiert.
  Ein erneuter Lauf überspringt bereits erfolgreiche Phasen.

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
uv run python protokoll_assistent/tools/laufzeit_pakete_pruefen.py
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
& .\runtime\venv\Scripts\python.exe -m pytest protokoll_assistent\tests -v
```

165 Tests decken u.a. ab: die hardwarebasierte Whisper-Modellempfehlung
(immer Turbo, Speicherhinweis, Diagnose-Auswertung), Chunk-Grenzen und
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
| GPU-Speicher reicht nicht | Fehlermeldung aus faster-whisper/pyannote, keine Rohdaten geloggt |
| Modell fehlt im Offline-Modus | Meldung; einmaliger Download nur nach bewusster Freigabe |
| HF_TOKEN fehlt bei Download | Verdeckte Abfrage, keine Speicherung |
| Ollama fehlt | Installer wird heruntergeladen und geöffnet, Nutzer schließt ihn ab |
| Ungültiger Ausgabeordner / Schreibfehler | Meldung vor Start, kein Datenverlust |
| Programmabbruch | Sicher über „Abbrechen" (wirkt nach aktuellem Chunk) |

Vollständige technische Details (niemals Tokens oder Audioinhalte) stehen in
`logs\protokoll_assistent.log`.

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
faster-whisper/PyTorch/pyannote/Ollama vorinstalliert):

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
- Die Oberfläche wird heute ohne Fenster geprüft: der Dienst über die
  Programmschnittstelle (`tests/test_api_*.py`), die Svelte-Oberfläche mit
  vitest, das Tauri-Fenster mit `cargo test`. (Die frühere PySide6-Oberfläche
  samt ihrer Offscreen-Qt-Tests ist im November 2026 entfernt worden.)
- `bootstrap.py` wurde mit vollständig simulierten (keine echten Downloads/
  Installationen) venv-/pip-/Python-Versions-Szenarien getestet: bereits
  vorhandene `.venv-whisperx` wird direkt verwendet, ein „frischer PC" legt
  `runtime\venv` an und installiert GPU- bzw. CPU-Pakete passend, der
  gebaute Dienst nimmt dafür das mitgelieferte Python, ein fehlgeschlagener
  Installationsschritt bricht sauber ab statt weiterzumachen.
- Der gebaute Dienst (`vermerk_dienst.spec`) wird vor jedem Release in der CI
  gestartet und mit Schlüssel abgefragt (`tools/dienst_rauchtest.py`).

**Nur auf einem echten Windows-Rechner testbar** (nicht behauptet, hier
getestet worden zu sein):

- Der tatsächliche automatische Download/Installation von PyTorch (GPU- oder
  CPU-Variante), faster-whisper, pyannote.audio auf einem wirklich neuen PC ohne
  vorbereitete Umgebung.
- Tatsächliche faster-whisper-Transkription, pyannote-Diarisierung und
  Ollama-Protokollerstellung mit echten Audiodateien.
- Der automatische FFmpeg- und Ollama-Installer-Download.
- Die gebaute `.exe` selbst (PyInstaller-Bündelung von faster-whisper/PyTorch/CUDA).
- Alle PowerShell-Skripte (`Einrichtung-Lokal.ps1`, `setup_lokal.ps1`,
  `check_pyannote_fix.ps1`) — PowerShell ist auf dieser Linux-Umgebung nicht
  verfügbar.
- Verhalten bei tatsächlich mehrstündigen Aufnahmen, echtem GPU-Speicherdruck
  und der realen pyannote-Kompatibilitätskorrektur an Ihrer installierten
  Version.
