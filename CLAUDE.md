# Hinweise für Claude Code

Diese Datei wird bei jeder Sitzung automatisch geladen. Sie hält fest, worauf
in diesem Projekt geachtet werden muss — inklusive der Gründe, damit klar ist,
wann eine Regel greift und wann nicht.

## Was das Projekt ist

**Eine** Windows-Anwendung (PySide6): `protokoll_assistent/`. Sie transkribiert
Besprechungsaufnahmen und wertet sie zu einem Protokoll aus.

Für beide Arbeitsschritte gibt es je zwei Wege, und die Wahl ist eine
**Einstellung**, kein eigenes Programm:

| Schritt | lokal | über eine API |
|---|---|---|
| Transkription | faster-whisper + pyannote | frei wählbarer Endpunkt (OpenAI-kompatibel) |
| Nachbearbeitung | Ollama | frei wählbarer Endpunkt (Chat-Completions) |

Gespeichert wird das in `protokoll_assistent/konfiguration.json`, bearbeitet im
Einstellungsdialog (`gui/settings_dialog.py`). Wer ausschließlich über eine API
arbeitet, braucht weder PyTorch noch ein Modell auf der Platte — die schwere
Laufzeitumgebung wird nur eingerichtet, wenn der Transkriptionsmodus beim Start
auf „lokal" steht.

### Vorgeschichte (wichtig beim Lesen alter Commits)

Bis September 2026 waren das **drei** getrennte Anwendungen: eine
tkinter-„Cloud-Variante" im Wurzelverzeichnis, eine PySide6-Anwendung in
`lokale_windows_app/` und eine dritte, „vereinte" in
`protokoll_assistent_vereint/`. Sie sind zu dieser einen zusammengeführt
worden; die tkinter-Variante ist ersatzlos entfallen, ihr API-Weg lebt als
Einstellung weiter. Wer in der Versionsgeschichte gräbt, findet diese Namen —
im aktuellen Stand gibt es sie nicht mehr.

## Vor dem Abschluss einer Aufgabe

```powershell
uv run ruff check .    # muss "All checks passed!" melden
uv run mypy            # muss "Success" melden
uv run pytest          # Tests
uv run pytest --cov    # bricht unter 85 % Abdeckung ab (so läuft es in der CI)
```

Alle laufen genauso in der CI (`.github/workflows/ci.yml`). Eine Aufgabe ist
nicht fertig, solange eines davon rot ist.

## Harte Regeln

### 1. Windows ist die Zielplattform — Tests müssen dort laufen

Die Anwendung läuft ausschließlich unter Windows. Die CI testet deshalb unter
Windows mit Python 3.10 **und** 3.11.

Keine POSIX-Annahmen in Tests. Konkret schon passiert:

```python
os.geteuid()                              # gibt es unter Windows nicht
assert str(pfad) == "/usr/bin/ffmpeg"     # pathlib normalisiert auf Backslashes
```

Pfade mit `Path`-Objekten vergleichen, nicht mit Zeichenketten. Rein
POSIX-spezifische Tests mit `@pytest.mark.skipif(os.name != "posix", ...)`
versehen und den Fehlerfall zusätzlich plattformunabhängig abdecken.

Windows kann außerdem beim **Ersetzen einer Datei** mit „Zugriff verweigert"
(WinError 5) scheitern, obwohl die Rechte stimmen — ein Virenscanner oder der
Suchindex hält die eben geschriebene Datei noch kurz offen. `save_manifest`
wiederholt den Versuch deshalb ein paar Mal
(`manifest_service._ersetzen_mit_wiederholung`). Wer eine weitere Stelle baut,
die eine Datei atomar ersetzt, braucht dieselbe Wiederholung — der Fehler tritt
zufällig auf und riss vorher ganze Verarbeitungsläufe ab.

### 2. Die Abdeckungsgrenze nicht senken und die Messung nicht verengen

`fail_under = 85` in `pyproject.toml` bleibt, wie es ist. Wenn die Abdeckung
fällt, fehlen Tests — nicht die Grenze ist falsch.

`[tool.coverage.run] source = ["."]` ebenfalls nicht durch eine Liste einzelner
Dateien ersetzen: coverage deutet Einträge, die kein Ordner sind, als
Modulnamen. Genau dadurch fielen `bootstrap.py`, `app.py`, `systempruefung.py`
und `modelle_herunterladen.py` einmal stillschweigend aus der Messung — die
gemeldete Zahl war zu hoch. Neue Ausnahmen gehören in `omit`, mit Begründung.

### 3. Keine Geheimnisse im Repository

API-Schlüssel und Hugging-Face-Token kommen aus Umgebungsvariablen, aus einer
verdeckten Eingabe (`getpass`) oder aus der
Windows-Anmeldeinformationsverwaltung — nie aus einer Datei im Repository, nie
als Standardwert im Code, nie in einer Logausgabe.

`services/secret_store.py` ist der **einzige** Ort, der `keyring` importiert.
Wer einen Schlüssel braucht, ruft die drei Funktionen dort auf. In
`konfiguration.json` steht nur, *ob* gemerkt werden soll — nie der Schlüssel
selbst.

`ausgabe/`, `aufnahmen/`, `arbeitsdaten/` und `logs/` bleiben außen vor — die
Anwendung legt sie beim Start selbst an.

gitleaks prüft in der CI auch die gesamte Versionsgeschichte.

### 4. Tests laufen ohne GPU, ohne Netz, ohne Modelle

PyTorch, faster-whisper und pyannote leben in der selbst eingerichteten
Laufzeitumgebung und stehen absichtlich **nicht** in der `dev`-Gruppe von
`pyproject.toml`. Die Dienste in `services/` nehmen ihre ML-Aufrufe als
Parameter entgegen, damit sie ersetzt werden können — dieses Muster
beibehalten. Genau daran hängt auch der API-Modus: `pipeline_service` bekommt
dort einfach andere Funktionen übergeben
(`transcribe_chunk_fn`/`diarize_fn`/`protocol_generate_fn`), die Ablaufsteuerung
bleibt dieselbe.

Kein Test darf etwas herunterladen, einen Netzwerkaufruf machen oder eine GPU
brauchen. Die ganze Suite läuft in Sekunden; das soll so bleiben.

### 5. Fenstertests

* Qt läuft unsichtbar über `QT_QPA_PLATFORM=offscreen`, gesetzt in
  `protokoll_assistent/tests/conftest.py`. Pro Prozess darf es nur eine
  `QApplication` geben — dafür ist die Fixture `qt_app` da.
* `QApplication` nie global über `monkeypatch` ersetzen: pytest-qt ruft in
  seinen Abbau-Haken `QApplication.instance()` auf und bricht dann ab. Wenn
  es sein muss, `unittest.mock.patch` als Kontextmanager **innerhalb** des
  Tests verwenden.
* **Keine Nebenfäden in Tests, die mit Fenstern zu tun haben.** Wartet eine
  Methode auf ein `threading.Event`, wird **nicht** per `threading.Timer`
  geantwortet. Stattdessen das Warten selbst ersetzen oder das Signal direkt
  mit seinem Empfänger verbinden, so wie es in der Anwendung auch läuft. Im
  Testbestand gibt es bewusst keinen einzigen `threading.Timer`.
* Tests dürfen **nicht** in die echte `konfiguration.json` schreiben.
  `app_config.get_config_file` wird dafür auf `tmp_path` umgebogen. Ohne das
  hinterlässt die Suite eine Datei im Arbeitsbaum und die Tests bestimmen sich
  gegenseitig das Ergebnis — genau das ist schon passiert (ein Test setzte
  `einrichtung_abgeschlossen`, der nächste sah deshalb den
  Einrichtungsassistenten nicht mehr).

**Wenn ein CI-Lauf ohne Testausgabe fehlschlägt**, ist das fast immer ein
Absturz des Prozesses und keine fehlgeschlagene Zusicherung. Dann im
Rohprotokoll des Jobs nach `fatal exception` suchen — die Zusammenfassung von
pytest fehlt in dem Fall.

### 6. Zeilenenden bleiben LF

`.gitattributes` schreibt LF vor. Windows-Werkzeuge — auch `ruff --fix` —
schreiben Dateien sonst mit CRLF zurück, und aus einer Zwei-Zeilen-Korrektur
wird ein Diff über die ganze Datei. Nach einem Massenlauf eines Formatierers
prüfen: `git diff --stat` darf nur die tatsächlich geänderten Zeilen zeigen.

### 7. Qt bleibt dynamisch eingebunden (LGPL)

PySide6 wird unter der **LGPL-3.0** benutzt. Damit das zulässig bleibt, muss
der Build ein **One-Directory-Build** bleiben: `exclude_binaries=True` plus
`COLLECT`, dazu `upx=False` und `strip=False`. Die Qt-Bibliotheken liegen dann
als eigene Dateien neben der EXE und lassen sich austauschen — genau das
verlangt die LGPL.

Nicht auf einen One-File-Build umstellen, nicht statisch linken, keine
Integritäts- oder Signaturprüfung über die Qt-DLLs legen. Jede dieser
Änderungen würde eine kommerzielle Qt-Lizenz nötig machen. Einzelheiten in
`NOTICES.md`.

Ebenfalls nicht tun: PySide6 durch **PyQt** ersetzen. PyQt gibt es nur unter
GPL oder kommerziell — für ein proprietäres Produkt wäre das schlechter, nicht
besser.

### 8. Die Installation der Anwender nicht anfassen

`protokoll_assistent/Einrichtung-Lokal.ps1`, `setup_lokal.ps1` und
`protokoll_assistent/requirements-anwendung.txt` sind der Weg, auf dem Anwender
die Anwendung installieren. `pyproject.toml` steht **zusätzlich** daneben und
gilt nur für Entwicklung und CI. Neue Laufzeit-Abhängigkeiten gehören in beide,
sonst fehlen sie den Anwendern.

Drei Paketlisten, drei Zwecke — bitte nicht vermischen:

* `requirements-anwendung.txt` — was die Anwendung selbst braucht (PySide6,
  python-docx, sounddevice, keyring). Reicht für den reinen API-Modus.
* `requirements-laufzeit.txt` — die schwere ML-Umgebung, die `bootstrap.py`
  bei Bedarf selbst einrichtet (Torch, faster-whisper, pyannote …).
* `requirements-torch.txt` — der CUDA-Index dazu.

### 9. Die Anwendung wird als Modul gestartet

`python -m protokoll_assistent.app`, nie über den Dateipfad. Ein Pfadstart legt
nur den Ordner der Datei in den Suchpfad; kein einziger Paketimport wäre
auflösbar. `bootstrap._relaunch` startet die Anwendung aus demselben Grund mit
`-m` und mit der Projektwurzel als Arbeitsverzeichnis.

`bootstrap.ensure_runtime_and_relaunch()` muss **vor** dem ersten Import von
PySide6/Torch laufen — daher die ungewöhnliche Importreihenfolge in `app.py`.
Diese Reihenfolge bitte so lassen.

### 10. Bestehendes nicht umbenennen oder durchformatieren

Bezeichner und Kommentare sind auf Deutsch — das bleibt so, auch in neuem
Code. Dateien, Funktionen und Ordner nicht umbenennen und die Projektstruktur
nicht umbauen.

Die Zusammenführung der drei Anwendungen im September 2026 war eine bewusste,
einmalige Ausnahme auf ausdrücklichen Wunsch — kein Freibrief für weitere
Umbauten.

`ruff format` **nicht** über den bestehenden Code laufen lassen: das schreibt
jede Datei neu und macht `git blame` wertlos. In der CI läuft
`ruff format --check` deshalb nur als Hinweis, ohne den Lauf rot zu machen.

Wenn eine Lint- oder Typ-Regel nur Rauschen erzeugt, lieber in
`pyproject.toml` mit einer Begründung abschalten, als den Code umzuschreiben.
Beispiele, die schon so gelöst sind: `S603`/`S607` (externe Programme werden
korrekt mit Argumentlisten statt `shell=True` aufgerufen) und `attr-defined`
für `protokoll_assistent.gui.*` (PySide6 liefert unvollständige Stubs).

### 11. Die CI kostet Geld

Das Repository ist **öffentlich**. Damit sind GitHub-Actions-Minuten
unbegrenzt und kostenlos, auch auf Windows-Läufern. Die Sparmaßnahmen von
früher (Prüfungen auf Linux, Abbruch überholter Läufe, nächtlicher Build nur
bei neuen Commits) sind trotzdem geblieben — sie machen die Rückmeldung
schneller, nicht nur billiger. Bitte nicht ohne Grund rückgängig machen.

Wird das Repository jemals wieder auf privat gestellt, kippt das: dann gelten
2000 Minuten im Monat, Windows zählt doppelt, und CodeQL, Secret Scanning und
die Branch-Schutzregeln fallen weg.

`ci.yml` läuft bei jedem Pull Request und bei jedem Push auf `main`. Damit ein
Branch mit offenem Pull Request nicht doppelt geprüft wird, ist die
`concurrency`-Gruppe auf den Branchnamen geschlüsselt — nicht auf `github.ref`.
Diese Gruppe bitte so lassen.

**Die CI blockiert das Zusammenführen.** Für `main` sind Branch-Schutzregeln
aktiv; diese Prüfungen müssen grün sein:

* Format, Linting und Typen
* Tests (Windows, Python 3.10) und (Windows, Python 3.11)
* Geheimnisse und Schwachstellen
* Laufzeit-Pakete der lokalen Anwendung
* Analyse (Python) — CodeQL

Dazu kommt `strict`: Der Branch muss auf dem Stand von `main` sein, bevor er
zusammengeführt werden darf. Das ist kein Schikane-Schalter — genau dieser Fall
ist schon einmal schiefgegangen: Ein Pull Request war grün, in der Zwischenzeit
kam auf `main` ein Test dazu, der einen Import benutzte, den der Pull Request
entfernt hatte. Git hat beides konfliktfrei zusammengeführt, die Datei war
trotzdem kaputt.

Beide Administratoren können die Regeln umgehen (`enforce_admins` ist aus),
damit sich niemand aussperrt. Das ist als Notausgang gedacht, nicht als
Normalweg.

### CodeQL: den Schalter „Code quality" in den Einstellungen NICHT umlegen

Im Reiter *Security* steht „Code quality" als *nicht aktiviert*. Das ist
**Absicht und kein Versäumnis.**

GitHub kennt für CodeQL zwei Betriebsarten, und sie schließen sich gegenseitig
aus:

* **Default setup** — GitHub verwaltet die Analyse selbst. Dazu gehört der
  Schalter „Code quality" in der Oberfläche.
* **Advanced setup** — ein eigener Workflow im Repository. Genau den benutzen
  wir: `.github/workflows/codeql.yml`, mit `queries: security-and-quality`.

Die Qualitätsabfragen laufen also **bereits** — daher stammen die offenen
Meldungen vom Typ `note`. Der Schalter in der Oberfläche gehört nur zur
anderen Betriebsart und ist über die API gar nicht erreichbar
(`"code_quality" is not a permitted key`).

Wird „Default setup" trotzdem eingeschaltet, übernimmt GitHub die Analyse und
unser Workflow läuft nicht mehr. Dann fehlt die Prüfung **„Analyse (Python)"**,
die für `main` erforderlich ist — und es lässt sich nichts mehr
zusammenführen, bis die Liste der erforderlichen Prüfungen angepasst ist.
Wer wirklich umstellen will, ändert beides zusammen.

## Weitere Dateien, die mitgepflegt werden wollen

* `CHANGELOG.md` — was sich fuer Anwender geaendert hat (Keep a Changelog).
  Neue Eintraege kommen unter `[Unreleased]`; beim Release wird daraus ein
  Versionsabschnitt. Die Version steht ausserdem in `pyproject.toml` und
  muss zum Tag passen.
* `SECURITY.md` — was in diesem Projekt sicherheitsrelevant ist und wie man
  eine Luecke meldet. Bei Aenderungen an der Datenuebertragung oder an den
  ausgeschlossenen Ordnern bitte dort nachziehen.
* `LICENSE` — der Quelltext ist oeffentlich lesbar, aber **nicht** zur Nutzung
  freigegeben. Keine Lizenzhinweise entfernen.
* `NOTICES.md` und `lizenzen/` — Hinweise zu fremder Software. Beide werden
  vom PyInstaller-Build **mit ausgeliefert** (siehe `datas` in
  `protokoll_assistent.spec`). Kommt eine Abhängigkeit dazu oder ändert
  sich eine Version, gehört das dort nachgetragen.
* `.github/CODEOWNERS`, `.github/pull_request_template.md` — Ablauf bei
  Pull Requests.
* `.github/workflows/codeql.yml` — CodeQL laeuft nur, solange das Repository
  oeffentlich ist.
* `installer/protokoll-assistent.iss` — der Inno-Setup-Installer. Er liefert
  die gebaute EXE **und** den Quelltext **und** eine eigene
  Python-Laufzeitumgebung aus: Die EXE genügt für den API-Modus, der lokale
  Modus richtet sich über `bootstrap.py` aus dem Quelltext heraus ein.

## Wo was liegt

```
protokoll_assistent.spec       PyInstaller-Spezifikation (baut das Paket)

protokoll_assistent/
  app.py                       Einstiegspunkt (ruft zuerst bootstrap auf!)
  bootstrap.py                 legt bei Bedarf die schwere ML-Laufzeit an
  gui/                         PySide6: Hauptfenster, Einstellungen,
                               Assistent, Dialoge, Worker
  services/                    Verarbeitungskette und API-Dienste, ohne Qt
  utils/                       Pfade, Konfiguration, Diagnose, Logging
  tests/                       die gesamte Testsuite
  einstellungen/               mitgelieferte Systemprompt-Vorlage
  requirements-*.txt           siehe Regel 8
```

Die Verarbeitungskette in `services/` kennt kein Qt. Das soll so bleiben:
Oberfläche und Logik sind getrennt, deshalb sind die Dienste ohne Fenster
testbar.
