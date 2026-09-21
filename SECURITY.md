# Sicherheit

## Eine Schwachstelle melden

Bitte melden Sie Sicherheitsluecken **nicht** ueber ein oeffentliches Issue.

Nutzen Sie stattdessen den Punkt **"Report a vulnerability"** im Reiter
*Security* dieses Repositorys. Die Meldung ist dann nur fuer die
Verantwortlichen sichtbar.

Wir melden uns innerhalb von 14 Tagen zurueck. Bitte geben Sie an:

* welche Version bzw. welchen Commit Sie geprueft haben,
* wie sich das Problem nachstellen laesst,
* welche Auswirkung Sie sehen.

Bitte geben Sie uns Zeit fuer eine Korrektur, bevor Sie die Luecke
veroeffentlichen.

## Was in diesem Projekt sicherheitsrelevant ist

Die Anwendung verarbeitet **Besprechungsaufnahmen** — also personenbezogene
Daten, oft von Menschen, die der Aufnahme nur im Rahmen der Besprechung
zugestimmt haben. Entsprechend gelten hier ein paar Punkte besonders:

* **Aufnahmen und Transkripte gehoeren niemals ins Repository.** Die Ordner
  `eingabe/`, `ausgabe/`, `zwischenstaende/` und `Ergebnis des Meetings wie
  gewünscht/` sind ausgeschlossen, ebenso Medien- und Protokolldateien
  ueberall im Baum.
* **`einstellungen/fachbegriffe.txt` ist ausgeschlossen**, weil dort
  Projektnamen und Nachnamen echter Personen stehen. Versioniert ist nur
  `fachbegriffe.beispiel.txt`.
* **Schluessel und Token stehen nie im Code und nie in einer Klartext-Datei.**
  Sie kommen aus Umgebungsvariablen (`OPENROUTER_API_KEY`, `HF_TOKEN`), aus
  einer verdeckten Eingabe (`getpass`), oder — nur in der vereinten
  Anwendung `protokoll_assistent_vereint/`, nur wenn der Anwender das
  ausdruecklich anhakt — dauerhaft ueber die Windows-Anmeldeinformations-
  verwaltung (Paket `keyring`, einziger Zugriffspunkt:
  `protokoll_assistent_vereint/services/secret_store.py`). Die
  Konfigurationsdatei dieser Anwendung
  (`protokoll_assistent_vereint/konfiguration.json`) enthaelt dabei nur ein
  Häkchen, ob gemerkt werden soll — nie den Schluessel selbst. Ohne dieses
  Häkchen gilt ein eingegebener Schluessel nur fuer die laufende Sitzung.
* **Die lokale Variante (`lokale_windows_app/`) uebertraegt keine Audio- oder
  Videodaten.** Bleibt das so, ist das eine Zusage an die Anwender — Aenderungen
  daran gehoeren ausdruecklich in die Release-Hinweise.
* **Die Cloud-Variante uebertraegt die Aufnahme** an einen vom Anwender
  gewaehlten Endpunkt. Vor jeder Uebertragung steht eine ausdrueckliche
  Rueckfrage. Diese Rueckfrage darf nicht entfallen.
* **Die vereinte Anwendung (`protokoll_assistent_vereint/`) uebertraegt im
  API-Modus ebenfalls die Aufnahme bzw. das Transkript** an einen vom
  Anwender gewaehlten Endpunkt — fuer Transkription und/oder
  Nachbearbeitung getrennt umschaltbar. Ist der API-Modus aktiv, zeigt die
  Oberflaeche dabei durchgehend einen Datenschutz-Hinweis: Fuer diese
  externe Schnittstelle kann keine Vertraulichkeit garantiert werden, die
  Verantwortung dafuer liegt beim Anwender. Der lokale Modus (faster-whisper/
  pyannote/Ollama) bleibt weiterhin vollstaendig offline.

## Was automatisch geprueft wird

Bei jedem Push auf jeden Branch (`.github/workflows/ci.yml`):

| Pruefung | Womit |
|---|---|
| Zugangsdaten im Code **und in der Historie** | gitleaks |
| Bekannte Schwachstellen in Abhaengigkeiten | pip-audit |
| Unsichere Muster im Code | Sicherheitsregeln (`S`) von ruff |
| Statische Codeanalyse | CodeQL (`.github/workflows/codeql.yml`) |

Zusaetzlich laeuft die Schwachstellenpruefung jede Nacht erneut
(`.github/workflows/nightly.yml`), weil neue Luecken auch ohne Aenderung am
Code bekannt werden. Dependabot meldet verwundbare Abhaengigkeiten und
schlaegt woechentlich Aktualisierungen vor.

## Unterstuetzte Versionen

Das Projekt ist noch jung. Sicherheitskorrekturen gibt es fuer den aktuellen
Stand des `main`-Branches.
