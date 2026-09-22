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
  `ausgabe/`, `aufnahmen/` und `arbeitsdaten/` sind ausgeschlossen, ebenso
  Medien- und Protokolldateien ueberall im Baum.
* **Schluessel und Token stehen nie im Code und nie in einer Klartext-Datei.**
  Sie kommen aus Umgebungsvariablen (`OPENROUTER_API_KEY`, `HF_TOKEN`), aus
  einer verdeckten Eingabe (`getpass`), oder — nur wenn der Anwender das
  ausdruecklich anhakt — dauerhaft ueber die Windows-Anmeldeinformations-
  verwaltung (Paket `keyring`, einziger Zugriffspunkt:
  `protokoll_assistent/services/secret_store.py`). Die Konfigurationsdatei
  (`protokoll_assistent/konfiguration.json`) enthaelt dabei nur ein
  Häkchen, ob gemerkt werden soll — nie den Schluessel selbst. Ohne dieses
  Häkchen gilt ein eingegebener Schluessel nur fuer die laufende Sitzung.
* **Im lokalen Modus werden keine Audio- oder Videodaten uebertragen.**
  Bleibt das so, ist das eine Zusage an die Anwender — Aenderungen daran
  gehoeren ausdruecklich in die Release-Hinweise.
* **Im API-Modus wird die Aufnahme bzw. das Transkript uebertragen** an einen
  vom Anwender gewaehlten Endpunkt — fuer Transkription und Nachbearbeitung
  getrennt umschaltbar. Ist fuer einen Schritt der API-Modus aktiv, zeigt die
  Oberflaeche durchgehend einen Datenschutz-Hinweis: Fuer diese externe
  Schnittstelle kann keine Vertraulichkeit garantiert werden, die
  Verantwortung dafuer liegt beim Anwender. Dieser Hinweis darf nicht
  entfallen.

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
