# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei
festgehalten.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionierung an [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Added

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
