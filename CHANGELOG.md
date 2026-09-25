# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei
festgehalten.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionierung an [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

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
