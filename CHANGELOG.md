# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei
festgehalten.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionierung an [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Added

- **Hugging-Face-Token aus `.env`:** Wer den Token nicht bei jedem Start als
  Umgebungsvariable setzen will, traegt ihn als `HF_TOKEN=...` in die `.env`
  im Programmordner ein (Vorlage `.env.beispiel`; die Datei ist von Git
  ignoriert). Eine gesetzte Umgebungsvariable hat Vorrang.
- **Frag mein Meeting:** Neuer Chatbot in der Seitenleiste. Links werden
  Transkripte und Zusammenfassungen angehakt, rechts stellt man Fragen; die
  Antworten stützen sich nur auf die ausgewählten Unterlagen und nennen ihre
  Quellen (Dokument und Uhrzeit). Dahinter arbeitet eine Suche in
  Textabschnitten (Einbettungen, zwischengespeichert) und ein Chatmodell.
- Neuer Reiter **Chatbot** in den Einstellungen: lokal (Ollama) oder API, mit
  Auswahl des Chatmodells und des Einbettungsmodells (BGE-M3, Nomic Embed
  Text, MixedBread, EmbeddingGemma oder eigener Name), Status und „Jetzt
  herunterladen“. Im API-Modus gibt es Endpunkt und Modell für Chat und
  Einbettungen sowie einen eigenen oder gemeinsamen Schlüssel; ein
  Datenschutzhinweis erscheint, weil dort Texte übertragen werden.
- **Frag mein Meeting – Hinweisleiste und Systemcheck:** Fehlt ein Modell, steht
  das als erster Hinweis oben auf der Seite, mit „Jetzt herunterladen“. Das
  Einbettungsmodell wird nur auf Wunsch geladen, nie von allein; der Hinweis
  verschwindet, sobald es da ist. Der Knopf „Systemcheck“ prüft Ollama bzw.
  den API-Zugang, die Modelle und macht je einen Probelauf für Suche und Antwort.
- **Gespeicherte Chats:** Jeder Chat wird automatisch gespeichert und steht links
  unter „Gespeicherte Chats“. Ein Klick öffnet ihn samt Nachrichten und den
  damals gewählten Unterlagen; Umbenennen und Löschen sind möglich.
  Die Dateien liegen lokal im Ordner `chatverlaeufe/` (nicht versioniert, nicht im Installer).
- **Rechner-Analyse als erster Schritt der lokalen Einrichtung:** Bevor etwas
  heruntergeladen wird, prüft das Programm Arbeitsspeicher, Prozessorkerne,
  die vorhandene Grafikkarte (egal von welchem Hersteller: NVIDIA, AMD, Intel,
  auch integrierte Grafik) und den freien Platz und bewertet jedes Modell
  (Transkription, Nachbearbeitung, Suche im Chat) mit „Läuft gut“, „Läuft
  langsam / knapp“ oder „Eher nicht geeignet“, samt Hinweisen und Empfehlung.
  Das empfohlene Sprachmodell wird für die Einrichtung vorausgewählt – eine
  bewusst getroffene Wahl in den Einstellungen bleibt unberührt. Es sind
  Schätzungen; jedes Modell lässt sich weiterhin wählen. Beschleunigen kann
  die Grafikkarte die Transkription nur bei NVIDIA (CUDA); eine Radeon-
  Einzelkarte kann Ollama bei der Nachbearbeitung helfen, wenn ihr Modell
  unterstützt wird, integrierte Grafik beschleunigt nichts – das erklärt die
  Analyse bei der erkannten Karte.
- **Systemtest: „Fehlendes nachladen“.** Fehlen FFmpeg, Ollama oder das
  Ollama-Modell, lädt ein Knopf sie herunter und zeigt den Grund, falls es
  scheitert; danach wird automatisch neu geprüft.

- **API-Anbieter zum Auswählen statt Voreinstellung:** In den Einstellungen
  (Transkription, Nachbearbeitung, Chatbot) wählt man den Anbieter aus einer
  Liste – IONOS, STACKIT, Mistral, Scaleway, Microsoft Azure, OpenAI, Anthropic
  (Claude), Google Gemini, Groq, OpenRouter oder „Eigener Endpunkt“ – und muss
  nur noch den API-Schlüssel eintragen. Adresse und Modellvorschlag werden
  eingesetzt; darunter stehen Standort, Hinweise und Links zum Schlüssel und
  zur Dokumentation. Die Transkription über eine API bleibt bei OpenRouter bzw.
  einem eigenen Endpunkt im selben Format (Audio im API-Aufruf, kein
  Dateiupload); die übrigen Anbieter gibt es für Nachbearbeitung und Chatbot.

- **Export in gängige Formate:** Der neue Knopf „Exportieren …“ (auf der
  Ergebnisseite und unter „Nachbearbeitung“) speichert Transkript, Protokoll
  oder beides in einem Dokument als Word, PDF, Markdown, Text, HTML oder
  OpenDocument – das Transkript zusätzlich als Untertitel (SRT, VTT) und JSON –
  in einen frei gewählten Ordner. Ziel und Formate werden für das nächste Mal
  gemerkt; vorhandene Dateien werden nie überschrieben.
- **Zusammengefasste Word-Datei von selbst:** Nach jeder Transkription entsteht
  neben den übrigen Ausgaben eine Word-Datei mit dem Transkript, nach der
  Nachbearbeitung eine mit Protokoll und Transkript in einem Dokument. Sie wird
  nach dem Umbenennen von Sprechern neu geschrieben. Scheitert das, bleibt die
  Verarbeitung gültig; der Grund steht im Protokoll.

- **Servermodus für Linux (Container):** Aufnahmen, die in einem Eingangsordner
  ankommen, werden automatisch in Chunks verarbeitet, transkribiert und
  zusammengefasst; Transkript, Protokoll und die zusammengefasste Word-Datei
  liegen danach in einem Ausgangsordner (`ergebnis.json` meldet den Ausgang,
  optional auch per Webhook). Läuft ohne Oberfläche per `docker compose`
  (Prozessor oder NVIDIA-Grafikkarte, Ollama als eigener Dienst); Einstellungen
  über Umgebungsvariablen. Anleitung: `protokoll_assistent/server/README.md`.

### Changed

- **OpenRouter ist nicht mehr voreingestellt.** Endpunkte und Modelle sind ab
  Werk leer, bis ein Anbieter gewählt wird; ohne Auswahl meldet das Programm
  „Kein Anbieter gewählt“, statt Aufnahmen oder Texte irgendwohin zu senden.
  Bereits gespeicherte Einstellungen bleiben erhalten und werden in der Liste
  richtig angezeigt.
- **Neues Standardmodell für die Nachbearbeitung: Qwen3.5 4B**
  (`qwen3.5:4b-q4_K_M`, etwa 3,3 GB) statt Qwen3 8B. Es ist trotz halber Größe
  leistungsfähiger und braucht weniger Speicher; das gilt auch für den Chatbot
  und den Servermodus.
- **Modellauswahl erneuert und verkleinert.** Zur Wahl stehen jetzt vier
  Modelle, alle unter Apache 2.0 und ausdrücklich in der Q4-Fassung:
  Qwen3.5 4B (Standard), **Qwen3.5 9B** (genauer, liegt in Tests vor dem
  bisherigen Qwen3 14B), **Gemma 4 12B** und für Rechner mit großer
  Grafikkarte (etwa 24 GB) **Qwen3.8 27B**. Entfallen sind Qwen3 4B, 8B und
  14B, Gemma 3, Llama 3.1 und Mistral Nemo; sie lassen sich weiterhin von Hand
  eintragen. Wer schon ein Modell gespeichert hat, behält es. Rechner mit
  weniger als etwa 7,8 GB Arbeitsspeicher bekommen bei der Einrichtung kein
  lokales Sprachmodell mehr empfohlen, sondern den Hinweis auf die API.
  Qwen3.5 und neuer brauchen ein aktuelles Ollama – bei einer älteren Fassung
  scheitert der Download.
- Die „Denkphase“ der Sprachmodelle wird jetzt über Ollama abgeschaltet
  (`think: false`). Das bisherige `/no_think` im Systemprompt verstehen
  Qwen3.5-Modelle nicht mehr; ohne die Änderung hätten sie vor jeder Antwort
  lange „nachgedacht“.
- **Aufgaben nur, wenn es welche gibt:** Der mitgelieferte Systemprompt sagt
  jetzt ausdrücklich, dass Forderungen, Meinungen und Vorschläge keine
  Aufgaben sind und die Liste bei Vorträgen, Diskussionen oder Interviews leer
  bleibt. Vorher dachte sich das Modell bei einer Podiumsdiskussion zehn
  „Aufgaben“ aus. Termine, offene Fragen und Fakten verlangt er als Text.

### Fixed

- **Lokale Protokolle aus vollständigem Text:** Die Nachbearbeitung über
  Ollama lief mit dessen Standard-Kontext von 4096 Tokens. Ein
  10-Minuten-Abschnitt samt Anweisung passt da oft nicht hinein; Ollama hat
  dann still den Anfang des Transkripts verworfen, und bei längeren
  Protokollen brach die Antwort mitten im JSON ab („Pflichtfeld fehlt“ bzw.
  „es fehlt jedes inhaltliche Feld“). Jetzt wählt die Anwendung die Größe je
  Aufruf: 16.384 Tokens für die Abschnitte, 32.768 für das Gesamtprotokoll.
  So bleibt das Modell auch auf kleinen Grafikkarten (6 GB) für die meisten
  Schritte ganz im Grafikspeicher. Gefunden durch die neuen Ende-zu-Ende-Tests.
- **Protokoll ohne Rohdaten:** Lieferte das Modell offene Fragen, Fakten oder
  Termine als Objekte statt als Text, standen sie mit geschweiften Klammern
  im Protokoll (Markdown, Word, PDF). Jetzt erscheinen sie als Satz mit den
  übrigen Angaben in Klammern.
- Ein gescheiterter FFmpeg-Download (kein Netz, Proxy, beschädigtes Paket)
  wurde in der Einrichtung nur still ins Protokoll geschrieben und die
  Einrichtung meldete trotzdem „abgeschlossen“. Jetzt wird die Lücke
  benannt (FFmpeg, Ollama, pyannote, Ollama-Modell).
- Ollama wurde direkt nach der Installation nicht gefunden, weil der neue
  PATH erst für neu gestartete Programme gilt. Die üblichen
  Installationsorte unter Windows werden jetzt mit durchsucht.

### Added

- Ollama-Modell wählbar: In den Einstellungen (Nachbearbeitung, lokal) gibt es
  jetzt eine Auswahl mit Qwen3 (4B, 8B, 14B), Gemma 3, Llama 3.1 und Mistral
  Nemo samt Größenangabe und Hinweis, dazu „Eigenen Modellnamen eingeben …“
  für jedes Modell aus der Ollama-Bibliothek. Der Status zeigt, ob das Modell
  installiert ist; „Jetzt herunterladen“ lädt es mit Fortschrittsanzeige
  nach. Vorausgewählt bleibt Qwen3 8B. Die lokale Ersteinrichtung lädt das
  hier eingestellte Modell, die Systemdiagnose prüft es, und die
  Nachbearbeitung meldet ein fehlendes Modell vor dem Start verständlich.

### Changed

- Seite „Transkription“ ohne Bildlauf: Links stehen Aufnahme und Datei, rechts
  die Einstellungen für den Lauf, das Fortsetzen und der Start. Aufnahmeknöpfe,
  Status und Pegel sitzen in einer Zeile, die Begrenzung der Sprecherzahl in
  einer Zeile, Erklärungen sind als Tooltips hinterlegt.

### Fixed

- Beim Speichern der Einstellungen erschien im lokalen Modus die Meldung, dass
  `keyring` fehlt, auch wenn der Anwender keinen Schlüssel merken wollte. Die
  Meldung kommt jetzt nur noch, wenn ein Schlüssel wirklich dauerhaft
  gespeichert werden soll. Zusätzlich installiert die selbst eingerichtete
  Laufzeitumgebung `keyring` jetzt mit, sodass das Merken dort funktioniert
  (beim nächsten Start einmalig mit Internetverbindung).

### Added

- Sehr lange Aufnahmen: Die Verdichtung der Teilanalysen (Stufe 2) läuft
  jetzt in mehreren Runden, bis das Ergebnis in den Kontext der
  Gesamtprotokoll-Stufe passt (höchstens 8 Runden). Vorher gab es genau eine
  Runde, und bei sehr langen Aufnahmen konnte das Kontextfenster des Modells
  überlaufen. Zwischenstände je Runde bleiben fortsetzbar.

- Sprecher anhören und exportieren: In der Sprechertabelle gibt es je
  Sprecher „▶ Anhören“ (kurze Hörprobe) und „Exportieren …“ (Audio als WAV
  und Text als TXT nur dieses Sprechers). Dafür speichert das JSON jetzt
  die Sprecherabschnitte (`sprecher_turns`) und den Pfad der aufbereiteten
  Audiodatei (`audio_pfad`). Transkripte aus älteren Versionen enthalten
  beides nicht; dort weist die Anwendung darauf hin, neu zu transkribieren.

- Dauerhafte Sprecherprofile (nur lokaler Modus): Stimmen lassen sich in der
  Sprechertabelle mit „Als Profil speichern“ merken, nach ausdrücklicher
  Bestätigung. In späteren Aufnahmen schlägt die Anwendung den Namen vor
  (mit Fragezeichen bei knapper Ähnlichkeit) und übernimmt ihn nur auf
  Klick. „Sprecherprofile verwalten …“ zeigt, benennt um und löscht Profile.
  Die Stimmabdrücke (biometrische Daten) liegen nur lokal im Ordner
  `sprecherprofile/`, der nicht versioniert und nicht in den Installer
  aufgenommen wird. Die Ähnlichkeitsschwelle (0,72) ist noch nicht an
  echten Aufnahmen abgestimmt.

- Fünf neue Protokollvorlagen mit festen Abschnitten und Erfindungsverbot:
  Formelles Protokoll, Projektbesprechung, Stand-up, Technische Besprechung
  und Interview. Sie legen fest, was in welches Feld des Protokolls gehört
  (z. B. Tagesordnungspunkte, Beschlüsse, Aufgaben mit Verantwortlichen und
  Fristen).

- Neue Dialoge: „Neue Transkription …“ fragt die Audioquelle ab (Mikrofon
  mit Geräteliste oder Mediendatei); vor „Transkription starten“ fragt
  „Verarbeitung wählen“ nach Sprechererkennung (automatisch oder bekannte
  Anzahl) und ob danach direkt das Protokoll mit einer Vorlage erstellt wird.

### Fixed

- Aufnahmegerät-Auswahl: Der Pfeil des Auswahlfelds öffnete bei leerer Liste
  nichts und sagte nicht, warum. Jetzt steht ein Platzhalter „Kein
  Aufnahmegerät verfügbar“ darin, der Grund steht darunter, und „Neu einlesen“
  liest die Geräte neu ein (z. B. nach dem Anstecken eines Headsets). Auswahllisten
  klappen unter dem Feld auf. Die gebaute EXE bündelt jetzt ausdrücklich
  `sounddevice` samt PortAudio-Bibliothek, und die selbst eingerichtete
  Laufzeitumgebung des lokalen Modus installiert es mit. Dort fehlte es, deshalb
  blieb die Geräteliste im lokalen Modus leer, auch bei angeschlossenem Gerät.
  Beim nächsten Start richtet sich die Umgebung einmalig neu ein (Internet nötig).
- Wer die Vorlage wechselte und die Nachbearbeitung erneut startete, bekam
  stillschweigend das fertige Protokoll der alten Vorlage zurück. Das
  Gesamtprotokoll wird jetzt neu erzeugt, sobald sich der Systemprompt
  ändert; Teilanalysen (Stufe 1 und 2) bleiben erhalten. Ein vorhandenes
  Protokoll aus einer älteren Version wird dabei einmal neu erzeugt.
- Die JSON-Struktur des Protokolls stand nur im mitgelieferten
  Standard-Systemprompt. Jede Vorlage und jeder freie Text ersetzt ihn
  vollständig - die letzte Stufe kannte die Struktur dann nicht. Sie wird
  jetzt in der Anfrage der letzten Stufe selbst mitgegeben.

### Changed

- Erscheinungsbild VERMERK: Das große Logo (Fassung für dunklen Grund) steht
  oben in der Seitenleiste, die Bildmarke ist Programmsymbol für Fenster,
  Dialoge, die EXE und den Installer. Die Dateien liegen in
  `protokoll_assistent/resources/` und entstehen mit
  `python -m protokoll_assistent.tools.logo_erzeugen` aus der EPS-Vorlage.
- Neues Hauptfenster mit Seitenleiste: Links stehen „Neue Transkription“, die
  Seiten **Transkription**, **Nachbearbeitung** und **Ergebnis und Sprecher**
  sowie unten „Ausgabeordner öffnen“ und „Einstellungen“. Die sieben
  Bereiche der alten linken Spalte sind auf diese Seiten verteilt; der
  Fortschritt steht kompakt unter jeder Seite. Schaltflächen sind überall
  gleich hoch und gleich gerundet (blau = Hauptaktion, weiß = Nebenaktion,
  rot = Abbrechen). Nach einer fertigen Transkription öffnet sich die Seite
  „Ergebnis und Sprecher“ von selbst.
- Oberfläche näher an moderne Arbeitsflächen gerückt: Titelzeile mit
  Untertitel, größere Rundungen, blauer Akzent, „Starten“-Schaltflächen
  hervorgehoben und „Abbrechen“/„Aufnahme beenden“ rot.
- Sprecherzuordnung wortgenau: Wechselt der Sprecher mitten in einem
  Segment, wird das Segment an dieser Stelle geteilt. Vorher ging das ganze
  Segment an den Sprecher mit der größten Überlappung, der Rest war falsch
  zugeordnet. Segmente ohne Wortzeitstempel (z. B. von API-Endpunkten, die
  nur Segmente liefern) werden wie bisher zugeordnet.

## [0.3.1] - 2026-09-25

### Fixed

- Der lokale Modus war in der gebauten EXE vollständig kaputt: Die
  selbsteinrichtende Laufzeitumgebung (Torch/faster-whisper/pyannote) wurde
  dort fälschlich übersprungen, in der Annahme, sie sei bereits gebündelt.
  Die erste Transkription scheiterte dadurch mit „ModuleNotFoundError: No
  module named 'torch'". Betrifft **nur** die EXE aus 0.3.0 — der reine
  API-Modus war davon nicht betroffen.
- Neu: Bei einer frischen Installation bietet die Anwendung die
  Ersteinrichtung des lokalen Modus (Systemtest, Modellempfehlung,
  Downloads) einmalig automatisch als Dialog über dem Hauptfenster an —
  lokale, private Verarbeitung bleibt damit auch ohne Blick in die
  Einstellungen leicht erreichbar.

## [0.3.0] - 2026-09-25

### Changed

- Die Anwendung zeigt beim Start immer sofort das Hauptfenster — nicht mehr
  erst den Einrichtungsassistenten davor

### Added

- Neuer Knopf „Einrichtung starten" im Einstellungen-Dialog (Reiter
  Transkription → Lokal): startet Download, Systemtest und Modellwahl gezielt,
  statt automatisch bei jedem ersten Programmstart

### Fixed

- Die Systemdiagnose zeigt jetzt live, welche Prüfung gerade läuft, statt
  während der gesamten Prüfung einen unveränderten „läuft ..."-Text
  anzuzeigen — bei einer frisch eingerichteten Laufzeitumgebung (Virenschutz
  prüft die eben geschriebenen PyTorch-/pyannote-Dateien) sah das wie ein
  Hängenbleiben aus

## [0.2.0] - 2026-09-22

Aus drei Anwendungen wird eine. Ob Transkription und Nachbearbeitung lokal
oder über eine Schnittstelle laufen, ist ab sofort eine **Einstellung** im
Programm — kein eigenes Programm, kein Auswahlfenster, keine zweite
Installation.

### Hinweise zur Umstellung

- Wer bisher die tkinter-Variante („Schnittstelle nutzen") verwendet hat,
  arbeitet künftig mit derselben Anwendung wie alle anderen und trägt
  Endpunkt und Schlüssel dort einmalig neu ein. **Bestehende Einstellungen
  werden nicht übernommen.**
- Gestartet wird über den Startmenü-Eintrag, `Start-Protokoll-Assistent.ps1`
  oder `python -m protokoll_assistent.app`. Ein Start über den reinen
  Dateipfad funktioniert nicht mehr.
- Die Anwendung liegt jetzt in `protokoll_assistent/` statt in
  `lokale_windows_app/`. Wer aus dem Quellcode installiert, passt seine
  Verknüpfungen entsprechend an.

### Added

- Systemprompt-Vorlagen lassen sich benannt speichern und im Hauptfenster
  auswählen
- API-Schlüssel können auf Wunsch dauerhaft in der
  Windows-Anmeldeinformationsverwaltung hinterlegt werden; ohne diese
  Zustimmung gelten sie nur für die laufende Sitzung
- Offline-Schalter im Hauptfenster: einmal abwählen, damit ein noch nicht
  eingerichtetes Whisper-Modell heruntergeladen werden darf

### Changed

- Transkription und Nachbearbeitung sind je einzeln auf „lokal" oder
  „Schnittstelle" umschaltbar — auch gemischt
- Alle Einstellungen stehen in **einer** `konfiguration.json`; vorher hatte
  jede Anwendung ihre eigene
- Der Systemprompt eines Laufs wird direkt an die Auswertung übergeben und
  überschreibt nicht mehr den gespeicherten Systemprompt
- Die Protokolldatei heißt `logs/protokoll_assistent.log`

### Removed

- Die tkinter-Variante samt Auswahlfenster, Konsolenversion und
  Einrichtungsfenster. Ihr Weg über eine Schnittstelle lebt als Einstellung
  weiter
- Die Fachbegriffsliste (`einstellungen/fachbegriffe.txt`); sie gab es nur in
  der tkinter-Variante

### Fixed

- Fehler des API-Modells (HTTP 401, nicht erreichbarer Endpunkt, Zeitlimit)
  werden als Protokollfehler gemeldet, statt als „Unerwarteter Fehler" zu
  erscheinen; Transkript und Bericht bleiben erhalten
- Eine Vorlage mit Zeichen, die Windows in Dateinamen verbietet („Wer macht
  was?"), wird mit einer verständlichen Meldung abgelehnt statt mit einem
  Absturz
- Das Speichern des Verarbeitungsstands wird wiederholt, wenn Windows die
  Datei kurzzeitig sperrt (Virenscanner) — vorher riss das ganze
  Verarbeitungsläufe ab
- Die Systemdiagnose prüft Platz und Schreibbarkeit des Ausgabeordners statt
  des Anwendungsordners
- Das im Einrichtungsassistenten gewählte Whisper-Modell gilt auch
  tatsächlich für die Transkription
- Die Anwendung startet auch dann, wenn `keyring` oder `sounddevice` in der
  Laufzeitumgebung fehlen; betroffen ist dann nur die jeweilige Zusatzfunktion

## [0.1.0] - 2026-09-21

### Added

- Erste Veröffentlichung: Transkription mit Sprechertrennung und
  anschließende Protokollauswertung, als vollständig lokale
  Windows-Anwendung und als Variante über eine Schnittstelle
- Installer für Windows (ohne Administratorrechte, mit mitgelieferter
  Python-Laufzeitumgebung)

[Unreleased]: https://github.com/Blickfeld-KevinLemaire/lokaler-protokoll-assistent/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/Blickfeld-KevinLemaire/lokaler-protokoll-assistent/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Blickfeld-KevinLemaire/lokaler-protokoll-assistent/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Blickfeld-KevinLemaire/lokaler-protokoll-assistent/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Blickfeld-KevinLemaire/lokaler-protokoll-assistent/releases/tag/v0.1.0
