# Gegenüberstellung: VERMERK (Protokoll-Assistent) und Meet2Notes

Stand: 29.09.2026. Verglichen wurden

* **VERMERK** = dieses Repository (`protokoll_assistent/`, Version 0.3.1,
  Commit `09da5ed`),
* **Meet2Notes** = <https://github.com/estebanstifli/Meet2Notes>, Version
  0.6.2, Commit `ace9f3d2f5454492c898a2e4d6da3359286dcfec` (28.09.2026),
  Lizenz MIT, „Copyright (c) 2026 Meet2Notes contributors".

**Versionsstand geprüft am 29.09.2026:** v0.6.2 ist der neueste Tag und
identisch mit `main` (Tags: v0.6.0 vom 24.08., v0.6.1 vom 10.09., v0.6.2 vom
28.09.2026). Der einzige weitere Branch
(`codex/audio-privacy-speaker-colors-seo`, letzter Commit 20.08.2026) ist
**älter** als v0.6.0 und enthält nichts Neueres. Die Neuerungen der
0.6er-Reihe sind in Abschnitt 3.4 einzeln bewertet.

Dieses Dokument ist die **Analyse vor der Integration**. Es ist noch kein
Meet2Notes-Code in VERMERK übernommen; Abschnitt 6 führt deshalb auf, was
übernommen werden *soll* und welche Lizenzpflichten dann entstehen.

---

## 1. Kurzfassung

* Die beiden Projekte lösen dasselbe Problem mit **grundverschiedener
  Architektur**: VERMERK ist eine PySide6-Desktopanwendung mit dateibasierter,
  fortsetzbarer Verarbeitungskette; Meet2Notes ist ein lokaler
  FastAPI-Webserver mit SQLite-Datenbank, Browser-Oberfläche, Plugin-System,
  RAG, MCP-Server und Webhooks.
* **Oberflächencode lässt sich nicht übernehmen** (HTML/Vanilla-JS gegen Qt).
  Übernehmbar sind *Abläufe*, *Datenmodelle* und einzelne, Qt-freie
  *Algorithmen*.
* Bei den Kernschritten — Aufnahme, Transkription, Diarisierung, lange
  Aufnahmen, Protokollerzeugung — ist VERMERK gleichwertig oder besser
  (fortsetzbare Chunks, globale Diarisierung, dreistufig validierte
  Protokollerzeugung, API-Modus). Hier wird **nichts ersetzt**.
* Echte Lücken von VERMERK, die Meet2Notes besser löst:
  1. **wortgenaue Sprecherzuordnung** bei Sprecherwechsel mitten im Segment,
  2. **dauerhafte Sprecherprofile** („gespeicherte Stimmen") über Besprechungen
     hinweg,
  3. **strukturierte Vorlagen** mit festen Abschnitten statt reinem Freitext,
  4. **Sprecher-Audio- und Sprecher-Text-Export** (Stimme anhören, bevor man
     einen Namen vergibt),
  5. optional: **Mikrofon + Systemton** gleichzeitig aufnehmen (WASAPI-Loopback).

### Wichtige Klarstellung zu „Sprecherprofilen"

Die Aufgabe verlangt, die vorhandenen VERMERK-Sprecherprofile beizubehalten.
**Dauerhafte Sprecherprofile gibt es im aktuellen Stand nicht** (weder auf
`main` noch auf einem anderen Branch). Vorhanden ist:

* die **Umbenennung pro Lauf** (`export_service.build_speaker_names`,
  `reexport_with_new_names`, Tabelle „Sprecherzuordnung" im Hauptfenster),
* die **Embedding-Zuordnung innerhalb eines Laufs** über Chunk-Grenzen
  (`speaker_merge_service.match_speakers_across_chunks`,
  `diarization_service.extract_speaker_embedding`, Kosinus-Ähnlichkeit,
  Schwelle 0,75, Unsicherheitsmarge 0,15).

Beides bleibt unverändert. Die dauerhaften Profile (Abschnitt 4.2) werden
**auf genau diesen beiden Bausteinen** aufgesetzt, nicht auf der
Sherpa-ONNX-Lösung von Meet2Notes — sonst gäbe es zwei Embedding-Modelle und
zwei Ähnlichkeitsfunktionen für dieselbe Aufgabe.

---

## 2. Rahmenbedingungen aus VERMERK, die jede Übernahme erfüllen muss

| Bedingung | Folge für Meet2Notes-Code |
|---|---|
| Python **3.10** und 3.11 (CI testet beide) | Meet2Notes verlangt ≥ 3.11 und nutzt `enum.StrEnum`, `asyncio`-Dienste. Übernommener Code muss auf 3.10 laufen → kein `StrEnum`, kein `asyncio`. |
| `services/` kennt kein Qt, ML-Aufrufe kommen als Parameter | Algorithmen werden als reine Funktionen übernommen, Modelle/FFmpeg als übergebene Funktion. |
| Tests ohne GPU, ohne Netz, ohne Modelle; Abdeckung ≥ 85 % | Jede Übernahme bringt eigene Tests mit Attrappen mit. |
| API-Modus braucht **kein numpy/Torch** (`requirements-anwendung.txt`) | Alles, was numpy braucht (z. B. `AudioMixer`), gehört in den lokalen Pfad oder muss ohne numpy auskommen. |
| Bezeichner und Kommentare auf Deutsch | Übernommener Code wird übersetzt und angepasst, nicht wörtlich eingefügt. |
| Keine Umbenennung, kein Umbau | Erweiterung bestehender Module; neue Module nur, wo es keinen passenden Ort gibt. |
| `secret_store.py` ist der einzige `keyring`-Nutzer | Meet2Notes-Credential-Code wird **nicht** übernommen. |
| Neue Laufzeitabhängigkeit → `pyproject.toml` **und** `requirements-*.txt`, `NOTICES.md`, `lizenzen/` | Siehe Abschnitt 6. |

---

## 3. Technische Gegenüberstellung

### 3.1 Architektur und Technik

| Bereich | VERMERK | Meet2Notes | Bewertung |
|---|---|---|---|
| Oberfläche | PySide6 (Qt 6), ein Hauptfenster, Einstellungsdialog, Assistent | FastAPI + Jinja2 + Vanilla-JS im Browser (`127.0.0.1:8765`) | Nicht übertragbar; nur Ideen/Abläufe |
| Schichten | `gui/` → `services/` → `utils/`, Dienste Qt-frei | `domain/` → `application/` → `infrastructure/` → `api/`/`web/`, Protokolle (`typing.Protocol`) | Gleiches Prinzip; VERMERK injiziert Funktionen, Meet2Notes Objekte |
| Persistenz | Dateien: `ausgabe/*.json|txt|srt|vtt`, `arbeitsdaten/<hash>/manifest.json`, `konfiguration.json` | SQLite (12 Migrationen), FTS5-Volltext, Vektor-BLOBs | Siehe 3.3 |
| Nebenläufigkeit | Qt-Worker-Thread (`gui/worker.py`), Abbruch per Callback | `asyncio`-Jobwarteschlange, je Engine eigener Thread-Pool | VERMERK für eine Desktop-App ausreichend |
| Python | 3.10–3.11 | ≥ 3.11 | Übernahmen müssen zurückportiert werden |
| Auslieferung | PyInstaller One-Dir + Inno Setup, Laufzeit per `bootstrap.py` | Git-Klon + venv per `install-update.bat`, Pinokio | VERMERK bleibt |
| Tests / Typen | pytest, mypy, ruff, 85 % Abdeckung, Windows-CI | pytest, mypy `strict`, ruff | gleichwertig |

### 3.2 Arbeitsschritte (Workflow)

| Schritt | VERMERK | Meet2Notes | Bewertung |
|---|---|---|---|
| Aufnahme | `recording_service.MikrofonAufnahme` (sounddevice, 16 kHz mono, WAV, Pause/Fortsetzen, Pegel, Geräteauswahl gemerkt) | Capture-Backends je Betriebssystem, **Mikrofon + Systemton** gemischt (`AudioMixer`, PyAudioWPatch/WASAPI-Loopback), Live-Pegel je Quelle | VERMERK-Architektur bleibt; Systemton als optionale Erweiterung (4.5) |
| Import | Datei/Ordner/Drag & Drop, FFmpeg-Normalisierung | Upload, FFmpeg-Probe und -Normalisierung | gleichwertig |
| Lange Aufnahmen | Chunks mit Überlappung, Manifest je Datei-Hash, **fortsetzbar** nach Abbruch, Deduplizierung an Chunk-Grenzen | ganze Datei; Jobs nach Neustart als fehlgeschlagen markiert | **VERMERK besser** |
| Transkription lokal | faster-whisper, Wortzeitstempel, Stapelverarbeitung | faster-whisper, NVIDIA-ASR, VibeVoice, Live-Modus | VERMERK ausreichend; Live-Transkription nicht Ziel |
| Transkription API | OpenAI-kompatibler Endpunkt, Wort→Segment-Gruppierung, Anbieter-Sprechertrennung | keine (nur lokal, LiteLLM nur für Analyse) | **VERMERK besser** |
| Diarisierung | pyannote **global** auf Gesamtaudio, Rückfall Embedding-Matching je Chunk | Sherpa-ONNX, pyannote-community, „diarize"; Sprecherturns in eigener Tabelle | VERMERK bleibt; Turns-Speicherung als Idee (4.1) |
| Sprecher ↔ Text | `assign_speakers_by_overlap`: **ganzes Segment** → Sprecher mit größter Überlappung | `speaker_turn_text`: Text **wortgenau** auf Turns zugeschnitten | **Meet2Notes besser** (4.1) |
| Sprecher benennen | Tabelle pro Lauf, Neuexport TXT/JSON/SRT/VTT | Speakers-Arbeitsbereich: umbenennen, als Stimme speichern, wiedererkennen, exportieren, Einzelzusammenfassung | **Meet2Notes umfangreicher** (4.2, 4.4) |
| Wiedererkennung | — | `SherpaOnnxSpeakerProfileMatcher`, Schwelle 0,72 | Lücke in VERMERK (4.2) |
| Nachbearbeitung | Ollama dreistufig (Chunk-Analyse → Zusammenführung → Endprotokoll), JSON-Schema-validiert, Zwischenstände zwischengespeichert; im API-Modus dieselbe Kette mit anderem Modell | llama.cpp oder LiteLLM; passt das Transkript ins Kontextfenster, **ein** Aufruf, sonst (seit 0.6.0) hierarchisch: Belegauszüge je Block → **wiederholte** Verdichtung, bis es passt (max. 8 Runden) → Endfassung; Markdown nach Vorlage, ohne Schema-Prüfung | **VERMERK besser** bei Prüfung und Fortsetzbarkeit; Meet2Notes besser bei sehr langen Aufnahmen und kurzen Transkripten (4.6); Vorlagen-Struktur besser (4.3) |
| Vorlagen | 3 eingebaute Freitext-Prompts + eigene `.txt` | 9 eingebaute Vorlagen mit **Abschnitten** (Titel, Anweisung, Format, Tabellenkopf) | Meet2Notes besser (4.3) |
| Export | TXT, JSON, SRT, VTT, Markdown, DOCX, Verarbeitungsbericht | Markdown, Sprecher-Text, **Sprecher-Audio** (WAV/MP3/FLAC) | Sprecher-Audio fehlt in VERMERK (4.4) |
| Bibliothek/Suche | Ordnerliste, keine Suche | Besprechungsbibliothek, FTS5, hybrides RAG, MCP | nicht übernehmen (Abschnitt 5) |
| Datenschutz-Hinweis | im Einstellungsdialog bei API-Modus | `docs/privacy.md`, MCP abschaltbar | gleichwertig |

### 3.3 Datenmodell

| Entität | VERMERK (JSON-Schlüssel) | Meet2Notes (Tabelle / Dataclass) |
|---|---|---|
| Besprechung | implizit: Quelldatei + `lauf_zeitstempel` | `meetings` / `Meeting` (uuid, Titel, Status, Dauer …) |
| Aufnahme | `quelldatei`, Datei-Hash im Manifest | `recordings` (Rolle original/normalized, sha256, Metadaten) |
| Transkript | `segmente[]` mit `start`, `end`, `text`, `words`, `sprecher_id`, `sprecher`, `chunk_index` | `transcriptions` + `transcript_segments` (ms-Ganzzahlen, `speaker_id`, `metadata.words`) |
| Sprecher je Lauf | `sprecher_zuordnung[]` (`sprecher_id`, `anzeigename`, Segmente, Sprechdauer) | `speakers` (display_name, `profile_id`, Zusammenfassung) |
| Sprecherturns | nur zur Laufzeit (`diarization_turns`) | `speaker_turns` (start_ms, end_ms, speaker_id) |
| Sprecherprofil | **fehlt** | `speaker_profiles` (Name eindeutig ohne Groß/Klein, `sample_path`, `embedding_path`) |
| Vorlage | Name → Freitext | `summary_templates` (system_prompt, user_prompt_template, sections) |
| Ergebnis | Protokoll-JSON (Themen, Entscheidungen, Aufgaben, Termine, offene Fragen, Quellen) | `summaries` (Markdown + optional `structured_json`) |
| Arbeitsstand | `manifest.json` je Datei-Hash, Chunk-Status | `jobs` (Status, Fortschritt, Abbruchwunsch) |

**Empfehlung:** Keine SQLite-Einführung. Das dateibasierte Modell ist für eine
Einzelplatz-Desktopanwendung ausreichend, fortsetzbar und ohne Migrationen
wartbar. Übernommen werden nur die **fehlenden Entitäten** — Sprecherprofil und
(im JSON) Sprecherturns — als zusätzliche Schlüssel bzw. eigene kleine
JSON-Dateien.

### 3.4 Neuerungen der 0.6er-Reihe einzeln bewertet

| Version | Neuerung (laut `CHANGELOG.md`) | Relevanz für VERMERK |
|---|---|---|
| 0.6.2 (28.09.) | Anna-Integration (Suche/Anzeige über den MCP-Zugang), eigener Ordner `integrations/anna/` | keine — baut auf MCP auf, das nicht übernommen wird; an Aufnahme, Transkription, Diarisierung und Notizen ändert 0.6.2 laut Changelog nichts |
| 0.6.1 (10.09.) | Mikrofon + Systemton gleichzeitig, uhrsynchroner 48-kHz-Mischer, getrennte Pegel je Quelle, Umgang mit getrennten Geräten und stummem Loopback | in 4.5 bewertet: gut, aber neue Abhängigkeiten; nur auf eigene Entscheidung |
| 0.6.0 (24.08.) | **Hierarchische Notizen**, wenn das Transkript das Kontextfenster übersteigt | **neu aufgenommen als 4.6** — wiederholte Verdichtung fehlt VERMERK |
| 0.6.0 | Notizen im Programm bearbeiten, speichern, frühere Fassungen behalten, manuelle Änderung kennzeichnen | Idee für später: Protokoll vor dem DOCX-Export in der Oberfläche korrigieren. Kein Code übertragbar (Web-UI) |
| 0.6.0 | MCP-Server, Meeting-Assistent mit RAG, Live-AI-Assistent | nicht übernehmen (Abschnitt 5) |
| 0.6.0 | Updater aus GitHub-Releases mit Sicherung und Rückfall | nicht übernehmen — VERMERK aktualisiert über den Inno-Setup-Installer |
| 0.6.0 | Plugin-Katalog der Community | nicht übernehmen |

---

## 4. Empfohlene Übernahmen (nach Nutzen geordnet)

### 4.1 Wortgenaue Sprecherzuordnung — *Code-Übernahme (angepasst)*

* **Quelle:** `src/local_meeting_ai/application/speaker_text.py`
  (`speaker_turn_text`, `_word_overlaps`).
* **Ziel:** `services/speaker_merge_service.py`, neue Funktion neben
  `assign_speakers_by_overlap`. Die bestehende Funktion bleibt als Rückfall für
  Segmente ohne Wortzeitstempel (API-Endpunkte ohne `words`).
* **Warum besser:** Spricht B mitten in einem Whisper-Segment von A, landet
  heute der ganze Satz bei A. Mit Wortzeitstempeln (liefert VERMERK bereits,
  `word_timestamps=True`) lässt sich das Segment am Sprecherwechsel teilen.
* **Anpassung:** Sekunden statt Millisekunden, dict-Segmente statt Dataclass,
  Rückgabe als geteilte Segmente (nicht nur Textfragmente), damit TXT/SRT/VTT
  unverändert weiterarbeiten.
* **Keine Doppelung:** ersetzt keine vorhandene Funktion, erweitert die eine
  Zuordnungsstelle.

### 4.2 Dauerhafte Sprecherprofile — *Datenmodell und Ablauf, eigener Code*

* **Vorbild:** `SpeakerProfile` (`domain/entities.py`), Migration
  `006_speaker_profiles.sql` (Name eindeutig, Groß-/Kleinschreibung egal),
  `SpeakerService.create_profile_from_speaker` / `rename_profile` /
  `delete_profile`, Abgleich in `adapters/diarization/profile_matching.py`.
* **Umsetzung in VERMERK:**
  * neues Modul `services/sprecherprofil_service.py` (Qt-frei): Profile als
    JSON unter einem neuen, **nicht versionierten** Ordner `sprecherprofile/`
    (in `.gitignore` und in `SECURITY.md` nachziehen — Stimmprofile sind
    biometrische Daten).
  * Gespeichert wird das **Embedding** (Liste von Floats, Modellname,
    Erstellungsdatum), optional eine kurze Stimmprobe. Meet2Notes speichert nur
    die WAV und rechnet bei jedem Abgleich neu; VERMERK hat das
    pyannote-Embedding ohnehin während der Diarisierung zur Hand.
  * Abgleich mit **vorhandenem** `cosine_similarity` und
    `extract_speaker_embedding`; Schwelle als Einstellung, Vorgabe wie
    `DEFAULT_MATCH_THRESHOLD`. Unsichere Treffer (Marge) werden nur
    *vorgeschlagen*, nie automatisch übernommen — gleiche Philosophie wie
    `match_speakers_across_chunks` („niemals willkürlich zusammenführen").
  * Nur im **lokalen** Modus; im API-Modus gibt es kein Embedding-Modell.
    Dort bleibt es bei der manuellen Benennung.
* **Oberfläche (Qt, eigene Umsetzung des Meet2Notes-Arbeitsbereichs „Speakers"):**
  in der bestehenden Tabelle „Sprecherzuordnung" eine Spalte „Erkannt als
  (Ähnlichkeit)" und die Schaltfläche „Als Sprecherprofil speichern"; ein
  kleiner Verwaltungsdialog (umbenennen, löschen) in `gui/dialogs.py`.
* **Nicht übernommen:** Sherpa-ONNX/3D-Speaker-Modell (zweites
  Embedding-Modell, weiterer Download), `asyncio`-Matcher.

### 4.3 Vorlagen mit Abschnitten — *Datenmodell + Prompt-Texte (übersetzt)*

* **Quelle:** `src/local_meeting_ai/application/summary_templates.py`
  (`BUILTIN_SUMMARY_TEMPLATES`, `render_summary_template`).
* **Ziel:** `utils/systemprompt_vorlagen.py`. Die drei vorhandenen
  Freitext-Vorlagen und die eigenen `.txt`-Vorlagen bleiben gültig; eine
  Vorlage *kann* zusätzlich Abschnitte haben, aus denen der Systemprompt
  gerendert wird („Nicht angegeben", wenn nichts belegt ist; nie Verantwortliche
  oder Fristen erfinden).
* **Warum besser:** reproduzierbare Gliederung, Tabellenköpfe für Aufgaben,
  ausdrückliches Erfindungsverbot je Abschnitt.
* **Kandidaten** (ins Deutsche übertragen): Formelles Protokoll
  (Formal Minutes), Projektbesprechung (Project Sync), Daily Stand-up,
  Technische Besprechung, Interview.
* **Abgrenzung:** Die dreistufige Ollama-Kette mit festem JSON-Schema
  (`protocol_service`) bleibt — sie prüft jede Antwort gegen ein Schema und
  setzt nach Abbruch fort, beides fehlt Meet2Notes. Zwei Ideen aus Meet2Notes'
  hierarchischer Zusammenfassung verbessern sie aber, siehe 4.6.

### 4.4 Sprecher-Audio- und Sprecher-Text-Export — *Code-Übernahme (angepasst)*

* **Quelle:** `infrastructure/ffmpeg.py` (`export_audio_ranges`,
  `_merge_audio_ranges`: `atrim` + `concat` über ein Filterskript),
  `SpeakerService.export_audio` / `export_text`.
* **Ziel:** `services/ffmpeg_service.py` (neue Funktion, synchron mit
  `subprocess.run` und Argumentliste wie die vorhandenen) und
  `services/export_service.py` (Sprecher-Text).
* **Nutzen:** Vor dem Benennen die Stimme anhören; Quelle für Stimmproben in
  4.2. Setzt voraus, dass die Turns im JSON-Export mitgespeichert werden
  (neuer Schlüssel `sprecherturns`, abwärtskompatibel lesbar).

### 4.5 Mikrofon + Systemton — *optional, eigene Entscheidung*

* **Vorbild:** `adapters/audio_capture/mixer.py` (uhrsynchrones Mischen mit
  Resampling, Drift-Korrektur, fester Aussteuerungsreserve),
  `windows_wasapi.py` (Loopback über PyAudioWPatch).
* **Bewertung:** qualitativ gut, aber
  * braucht **numpy** im Anwendungspaket (heute nur in der ML-Laufzeit),
  * braucht **PyAudioWPatch** (MIT, PortAudio-Fork) *neben* sounddevice — zwei
    PortAudio-Bindungen im selben Prozess,
  * `MikrofonAufnahme` müsste um eine zweite Quelle erweitert werden.
* **Empfehlung:** Die VERMERK-Recorder-Architektur bleibt. Falls gewünscht,
  als *zweite, optionale Quelle* in `recording_service` ergänzen, nachdem
  geprüft ist, ob sounddevice/PortAudio in der ausgelieferten Version
  WASAPI-Loopback selbst beherrscht (dann ohne PyAudioWPatch). Vorher nicht
  umsetzen.

### 4.6 Verdichtung bis es passt — *Ablauf-Idee, eigener Code (neu seit 0.6.0)*

* **Vorbild:** `adapters/summary/llama_cpp.py`, `_hierarchical_summary`,
  `_fits_context`, `_pack_reports_for_context`.
* **Lücke in VERMERK:** `protocol_service.run_full_protocol_pipeline`
  verdichtet in Stufe 2 genau **einmal** in Vierergruppen. Bei einer sehr
  langen Aufnahme (z. B. 40 Chunks → 10 Zwischenanalysen) bekommt Stufe 3
  alle 10 auf einmal — das kann das Kontextfenster eines lokalen
  Ollama-Modells sprengen. Meet2Notes wiederholt die Verdichtung, bis das
  Ergebnis passt, mit fester Obergrenze an Runden.
* **Umsetzung:** Stufe 2 in einer Schleife, bis höchstens `group_size`
  Zwischenanalysen übrig sind; jede Runde mit eigenem Zwischenspeicher
  (`zwischenanalyse_r<runde>_<nr>.json`), damit das Fortsetzen erhalten bleibt;
  Obergrenze gegen Endlosschleifen. Schema-Prüfung (`generate_validated`)
  unverändert.
* **Optional zweitens:** Passt ein kurzes Transkript ganz ins Kontextfenster,
  Stufe 1 und 2 überspringen (weniger Aufrufe, schneller). Dafür bräuchte
  VERMERK eine Kontextgröße je Modell als Einstellung; deshalb nachrangig.
* **Keine Doppelung:** ändert nur die Gruppierung in der vorhandenen Kette,
  kein zweiter Zusammenfassungsweg. Kein Code übernommen → keine
  Lizenzpflicht, Hinweis in `NOTICES.md` nur zur Transparenz.

---

## 5. Bewusst **nicht** übernommen

| Meet2Notes-Komponente | Grund |
|---|---|
| Web-Oberfläche (FastAPI, Jinja2, JS, CSS) | andere Oberflächentechnik; VERMERK ist Qt |
| SQLite-Repositories, Migrationen, FTS5 | dateibasiertes Modell reicht; Umbau widerspräche Regel 10 |
| Jobwarteschlange (`infrastructure/jobs.py`) | Doppelung zu Manifest + Qt-Worker |
| Transkriptions-Engines (faster-whisper-Adapter, NVIDIA-ASR, VibeVoice) | faster-whisper ist vorhanden; weitere Engines = neue schwere Abhängigkeiten |
| Diarisierung Sherpa-ONNX / pyannote-community / diarize | pyannote-Weg vorhanden; zweites Modell wäre Doppelung |
| llama.cpp-/LiteLLM-Zusammenfassung | Ollama- und API-Weg vorhanden |
| Credential-Speicher (`adapters/summary/credentials.py` u. a.) | Regel 3: nur `secret_store.py` |
| Live-Transkription, Live-AI-Assistent | nicht Ziel der Anwendung; hoher Aufwand |
| RAG, MCP-Server, Webhooks | Datenabfluss-Risiko, neue Abhängigkeiten (`mcp`, `fastembed`, `sqlite-vec`), eigenes Produktfeld |
| Plugin-System (Entry Points) | für eine ausgelieferte EXE nicht sinnvoll |
| Installer/Updater (`install-update.bat`, `updater.py`, Pinokio) | Inno Setup + `bootstrap.py` vorhanden |
| Modell-Download/-Verwaltung | `model_service` / `model_download_service` vorhanden |

---

## 6. Open-Source-Komponenten und Lizenzhinweise

### 6.1 Aus Meet2Notes übernommen bzw. zur Übernahme vorgesehen

| # | Meet2Notes-Datei (Commit `ace9f3d`) | Art der Übernahme | Ziel in VERMERK | Status |
|---|---|---|---|---|
| 1 | `application/speaker_text.py` | Algorithmus, angepasst und übersetzt | `services/speaker_merge_service.py` | geplant |
| 2 | `infrastructure/ffmpeg.py` (`export_audio_ranges`, `_merge_audio_ranges`) | Algorithmus, angepasst | `services/ffmpeg_service.py` | geplant |
| 3 | `application/summary_templates.py` | Vorlagenstruktur und Prompt-Texte, übersetzt | `utils/systemprompt_vorlagen.py` | geplant |
| 4 | `domain/entities.py` (`SpeakerProfile`), `sql/006_speaker_profiles.sql`, `application/speaker_service.py` | nur Datenmodell/Ablauf als Vorbild, **eigener Code** | `services/sprecherprofil_service.py` | geplant |
| 5 | `adapters/audio_capture/mixer.py` | ggf. Algorithmus | `services/recording_service.py` | offen (4.5) |
| 6 | `adapters/summary/llama_cpp.py` (`_hierarchical_summary`) | nur Ablauf als Vorbild, **eigener Code** | `services/protocol_service.py` | geplant (4.6) |

Lizenz aller Einträge: **MIT**, Copyright (c) 2026 Meet2Notes contributors.

### 6.2 Was die MIT-Lizenz verlangt und wie es erfüllt wird

Die MIT-Lizenz erlaubt Nutzung, Änderung und Weitergabe — auch in einem nicht
freien Produkt wie VERMERK (siehe `LICENSE`) — unter **einer** Bedingung: Der
Urheberrechtsvermerk und der Lizenztext müssen in allen Kopien oder
wesentlichen Teilen enthalten sein.

Sobald die erste der Übernahmen aus 6.1 umgesetzt wird:

1. `lizenzen/meet2notes-mit.txt` mit dem **vollständigen, unveränderten**
   MIT-Text aus dem Meet2Notes-Repository anlegen. Der Ordner `lizenzen/` wird
   laut `protokoll_assistent.spec` mit ausgeliefert.
2. In `NOTICES.md`, Abschnitt „Im Programm enthalten", einen Eintrag
   **Meet2Notes** mit Lizenz, Urheber, Quell-URL, Commit und der Liste der
   betroffenen VERMERK-Dateien ergänzen.
3. In jeder betroffenen VERMERK-Datei einen Kopfkommentar:
   „Teile angepasst übernommen aus Meet2Notes (<Datei>, Commit ace9f3d),
   MIT-Lizenz, Copyright (c) 2026 Meet2Notes contributors — siehe
   `lizenzen/meet2notes-mit.txt`."
4. Bei Übernahme 4 und 6 (nur Vorbild, eigener Code) entsteht keine Lizenzpflicht;
   der Hinweis in `NOTICES.md` wird der Transparenz halber trotzdem geführt.
5. Meet2Notes-Name und -Logo werden **nicht** verwendet (MIT gewährt keine
   Markenrechte).

### 6.3 Mittelbar betroffene Pakete

Die Übernahmen 1–4 bringen **keine neue Abhängigkeit** mit — sie nutzen
vorhandene Bausteine (FFmpeg, pyannote, python-docx). Nur Übernahme 5 würde
neue Pakete erfordern:

| Paket | Lizenz | nötig für | Pflichten |
|---|---|---|---|
| numpy | BSD-3-Clause | 4.5 (`AudioMixer`) im Anwendungspaket | Lizenztext in `lizenzen/`, Eintrag `NOTICES.md`, `requirements-anwendung.txt` + `pyproject.toml` |
| PyAudioWPatch (enthält PortAudio) | MIT | 4.5, nur falls sounddevice kein Loopback kann | wie oben |

Ausdrücklich **nicht** benötigt, weil nicht übernommen: sherpa-onnx
(Apache-2.0), 3D-Speaker-Modell (Apache-2.0), llama-cpp-python (MIT), LiteLLM
(MIT), fastembed (Apache-2.0), BGE-M3 (MIT), sqlite-vec (MIT/Apache-2.0),
FastAPI (MIT), mcp (MIT).

---

## 7. Vorgeschlagene Reihenfolge

1. **4.1 Wortgenaue Sprecherzuordnung** — kleinster Eingriff, sofort
   bessere Transkripte, keine UI-Änderung. Zugleich `lizenzen/` und
   `NOTICES.md` nach 6.2 anlegen.
2. **4.4 Sprecherturns im JSON + Sprecher-Audio-Export** — Voraussetzung
   für 4.2.
3. **4.2 Sprecherprofile** — Dienst, Tabelle, Verwaltungsdialog;
   `SECURITY.md` und `.gitignore` nachziehen.
4. **4.3 Vorlagen mit Abschnitten.**
5. **4.6 Wiederholte Verdichtung** — klein, betrifft nur `protocol_service`;
   kann auch vorgezogen werden, wenn lange Aufnahmen heute am Kontextfenster
   scheitern.
6. **4.5 Systemton** — nur nach eigener Entscheidung.

Jeder Schritt als eigener Pull Request mit Tests (ohne GPU/Netz/Modelle),
`CHANGELOG.md`-Eintrag unter `[Unreleased]` und grüner CI.
