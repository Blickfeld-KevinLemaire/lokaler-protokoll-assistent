# Hinweise für Claude Code

Diese Datei wird bei jeder Sitzung automatisch geladen. Sie hält fest, worauf
in diesem Projekt geachtet werden muss — inklusive der Gründe, damit klar ist,
wann eine Regel greift und wann nicht.

## Was das Projekt ist

Zwei eigenständige Anwendungen, die sich nichts teilen außer der Sprache:

| | Ordner | Technik |
|---|---|---|
| Cloud-Variante | Projektwurzel (`protokoll_assistent_gui.py`, `protokoll_assistent_v2.py`) | tkinter, Transkription über einen frei wählbaren API-Endpunkt |
| Lokale Variante | `lokale_windows_app/` | PySide6, faster-whisper + pyannote + Ollama, vollständig offline |

Beide werden aktiv gepflegt. Die lokale Variante ist **kein** Nachfolger der
Cloud-Variante — wer keine Daten aus der Hand geben will, nimmt die lokale;
wer keine KI-Modelle installieren will, die Cloud-Variante.

### Dritte, vereinte Anwendung (in Aufbau)

`protokoll_assistent_vereint/` ist eine **dritte**, neue PySide6-Anwendung,
die lokal (faster-whisper/pyannote/Ollama) und API-basierte Transkription
und Nachbearbeitung in **einer** Oberfläche vereint — die Wahl ist dort eine
Einstellung, kein separater Programmstart. Sie läuft **neben** den beiden
obigen Anwendungen, verändert keine ihrer Dateien und importiert
`lokale_windows_app`s Verarbeitungskette (`services/`, `utils/`) unverändert
wieder — eigene Module dieser dritten App werden dabei immer qualifiziert
importiert (`protokoll_assistent_vereint.X.Y`), nie bare, um nicht mit den
bare `services`/`utils`/`gui`-Paketen von `lokale_windows_app` auf demselben
`sys.path` zu kollidieren. API-Schlüssel können dort optional über die
Windows-Anmeldeinformationsverwaltung gemerkt werden (`keyring`, einziger
Zugriffspunkt `protokoll_assistent_vereint/services/secret_store.py`) — nie
als Klartext-Datei.

Sobald sich diese dritte Anwendung bewährt hat, sollen beide obigen Apps
damit abgelöst werden. Das ist eine **eigene, spätere** Planungs- und
Freigaberunde (Installer, CI, `hauptanwendung.py`, dieser Abschnitt hier) —
bis dahin bleibt die Tabelle oben der gültige Ist-Zustand der beiden
bestehenden Anwendungen.

## Vor dem Abschluss einer Aufgabe

```powershell
uv run ruff check .    # muss "All checks passed!" melden
uv run mypy            # muss "Success" melden
uv run pytest          # bricht unter 85 % Abdeckung ab
```

Alle drei laufen genauso in der CI (`.github/workflows/ci.yml`). Eine Aufgabe
ist nicht fertig, solange eines davon rot ist.

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

### 2. Die Abdeckungsgrenze nicht senken und die Messung nicht verengen

`fail_under = 85` in `pyproject.toml` bleibt, wie es ist. Wenn die Abdeckung
fällt, fehlen Tests — nicht die Grenze ist falsch.

`[tool.coverage.run] source = ["."]` ebenfalls nicht durch eine Liste einzelner
Dateien ersetzen: coverage deutet Einträge, die kein Ordner sind, als
Modulnamen. Genau dadurch fielen `bootstrap.py`, `app.py`, `Systempruefung.py`
und `Modelle-herunterladen.py` einmal stillschweigend aus der Messung — die
gemeldete Zahl war zu hoch. Neue Ausnahmen gehören in `omit`, mit Begründung.

### 3. Keine Geheimnisse im Repository

API-Schlüssel und Hugging-Face-Token kommen aus Umgebungsvariablen oder aus
einer verdeckten Eingabe (`getpass`) — nie aus einer Datei im Repository, nie
als Standardwert im Code, nie in einer Logausgabe.

`einstellungen/fachbegriffe.txt` ist bewusst ignoriert (dort stehen
Projektnamen und Nachnamen echter Personen). Nur
`fachbegriffe.beispiel.txt` wird versioniert. Ebenso bleiben `eingabe/`,
`ausgabe/`, `zwischenstaende/` und `Ergebnis des Meetings wie gewünscht/`
außen vor — die Anwendungen legen sie beim Start selbst an.

gitleaks prüft in der CI auch die gesamte Versionsgeschichte.

### 4. Tests laufen ohne GPU, ohne Netz, ohne Modelle

PyTorch, faster-whisper und pyannote leben in `.venv-whisperx` und stehen
absichtlich **nicht** in der `dev`-Gruppe von `pyproject.toml`. Die Dienste in
`lokale_windows_app/services/` nehmen ihre ML-Aufrufe als Parameter entgegen,
damit sie ersetzt werden können — dieses Muster beibehalten.

Kein Test darf etwas herunterladen, einen Netzwerkaufruf machen oder eine GPU
brauchen. Die ganze Suite läuft in Sekunden; das soll so bleiben.

### 5. Fenster testen

* **tkinter:** Die Fixture `tk_wurzel` (in `tests/conftest.py`) liefert ein
  verstecktes Fenster. Modale Dialoge (`wait_window`) blockieren den Test —
  sie werden über `root.after` ferngesteuert, siehe `_dialog_fernsteuern` in
  `tests/test_protokoll_assistent_gui_fenster.py`.
* **Qt:** Läuft unsichtbar über `QT_QPA_PLATFORM=offscreen`, gesetzt in
  `lokale_windows_app/tests/conftest.py`. Pro Prozess darf es nur eine
  `QApplication` geben — dafür ist die Fixture `qt_app` da.
* `QApplication` nie global über `monkeypatch` ersetzen: pytest-qt ruft in
  seinen Abbau-Haken `QApplication.instance()` auf und bricht dann ab. Wenn
  es sein muss, `unittest.mock.patch` als Kontextmanager **innerhalb** des
  Tests verwenden.
* pytest läuft mit `--capture=sys`. Fängt pytest die Ausgabe auf Ebene der
  Dateideskriptoren ab, kann Tcl/Tk unter Windows die Theme-Datei von sv-ttk
  nicht mehr laden. Diese Einstellung nicht ändern.
* **Keine Nebenfäden in Tests, die mit Fenstern zu tun haben.** Räumt Python
  in einem Nebenfaden zufällig ein Tk-Objekt weg, bricht Tcl den gesamten
  Prozess ab:

  ```
  Tcl_AsyncDelete: async handler deleted by the wrong thread
  Windows fatal exception: code 0x80000003
  ```

  Ob das passiert, hängt vom Zeitpunkt der Speicherbereinigung ab — genau
  deshalb ist der Fehler lokal und unter Python 3.10 durchgerutscht und erst
  unter 3.11 in der CI aufgeschlagen. Wegen `--capture=sys` ging dabei auch
  die ganze Testausgabe verloren; im Protokoll stand nur der Exit-Code.

  Wartet eine Methode auf ein `threading.Event`, wird **nicht** per
  `threading.Timer` geantwortet. Stattdessen das Warten selbst ersetzen
  (`_SofortigesEreignis` in `tests/test_protokoll_assistent_gui_fenster.py`)
  oder das Signal direkt mit seinem Empfänger verbinden, so wie es in der
  Anwendung auch läuft. Im Testbestand gibt es bewusst keinen einzigen
  `threading.Timer` mehr.

**Wenn ein CI-Lauf ohne Testausgabe fehlschlägt**, ist das fast immer ein
Absturz des Prozesses und keine fehlgeschlagene Zusicherung. Dann im
Rohprotokoll des Jobs nach `fatal exception` oder `Tcl_AsyncDelete` suchen —
die Zusammenfassung von pytest fehlt in dem Fall.

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

`Protokoll-Assistent-Einrichten.bat`, `lokale_windows_app/setup_lokal.ps1`,
`requirements.txt` und `requirements-local-gui.txt` sind der Weg, auf dem
Anwender die Anwendung installieren. `pyproject.toml` steht **zusätzlich**
daneben und gilt nur für Entwicklung und CI. Neue Laufzeit-Abhängigkeiten
gehören in beide, sonst fehlen sie den Anwendern.

### 9. Bestehendes nicht umbenennen oder durchformatieren

Bezeichner und Kommentare sind auf Deutsch — das bleibt so, auch in neuem
Code. Dateien, Funktionen und Ordner nicht umbenennen und die Projektstruktur
nicht umbauen.

`ruff format` **nicht** über den bestehenden Code laufen lassen: das schreibt
jede Datei neu und macht `git blame` wertlos. In der CI läuft
`ruff format --check` deshalb nur als Hinweis, ohne den Lauf rot zu machen.

Wenn eine Lint- oder Typ-Regel nur Rauschen erzeugt, lieber in
`pyproject.toml` mit einer Begründung abschalten, als den Code umzuschreiben.
Beispiele, die schon so gelöst sind: `S603`/`S607` (externe Programme werden
korrekt mit Argumentlisten statt `shell=True` aufgerufen) und `arg-type` für
die tkinter-Module (`widget.pack(**pad)` lässt sich mit typeshed grundsätzlich
nicht prüfen).

### 10. Die CI kostet Geld

Das Repository ist **öffentlich**. Damit sind GitHub-Actions-Minuten
unbegrenzt und kostenlos, auch auf Windows-Läufern. Die Sparmaßnahmen von
früher (Prüfungen auf Linux, Abbruch überholter Läufe, nächtlicher Build nur
bei neuen Commits) sind trotzdem geblieben — sie machen die Rückmeldung
schneller, nicht nur billiger. Bitte nicht ohne Grund rückgängig machen.

Wird das Repository jemals wieder auf privat gestellt, kippt das: dann gelten
2000 Minuten im Monat, Windows zählt doppelt, und CodeQL, Secret Scanning und
die Branch-Schutzregeln fallen weg.

`ci.yml` läuft bei jedem Push auf **jeden** Branch, damit ein Stand schon
geprüft ist, bevor daraus ein Pull Request wird. Damit ein Branch mit offenem
Pull Request nicht doppelt geprüft wird, ist die `concurrency`-Gruppe auf den
Branchnamen geschlüsselt — nicht auf `github.ref`. Diese Gruppe bitte so
lassen.

**Die CI blockiert das Zusammenführen.** Für `main` sind Branch-Schutzregeln
aktiv; diese Prüfungen müssen grün sein:

* Format, Linting und Typen
* Tests (Windows, Python 3.10) und (Windows, Python 3.11)
* Geheimnisse und Schwachstellen
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

Die Anzahl dieser Meldungen stand hier früher als feste Zahl. Das ist
bewusst entfernt: Sie ändert sich mit jedem Commit, der ein `except: pass`
hinzufügt oder entfernt, und eine veraltete Zahl in der Anleitung ist
schlechter als gar keine. Der aktuelle Stand steht im Reiter *Security*
oder kommt aus
`gh api repos/<owner>/<repo>/code-scanning/alerts?state=open`.

Wird „Default setup" trotzdem eingeschaltet, übernimmt GitHub die Analyse und
unser Workflow läuft nicht mehr. Dann fehlt die Prüfung **„Analyse (Python)"**,
die für `main` erforderlich ist — und es lässt sich nichts mehr
zusammenführen, bis die Liste der erforderlichen Prüfungen angepasst ist.
Wer wirklich umstellen will, ändert beides zusammen.

## Weitere Dateien, die mitgepflegt werden wollen

* `SECURITY.md` — was in diesem Projekt sicherheitsrelevant ist und wie man
  eine Luecke meldet. Bei Aenderungen an der Datenuebertragung oder an den
  ausgeschlossenen Ordnern bitte dort nachziehen.
* `LICENSE` — der Quelltext ist oeffentlich lesbar, aber **nicht** zur Nutzung
  freigegeben. Keine Lizenzhinweise entfernen.
* `NOTICES.md` und `lizenzen/` — Hinweise zu fremder Software. Beide werden
  vom PyInstaller-Build **mit ausgeliefert** (siehe `datas` in
  `protokoll_assistent_lokal.spec`). Kommt eine Abhängigkeit dazu oder ändert
  sich eine Version, gehört das dort nachgetragen.
* `.github/CODEOWNERS`, `.github/pull_request_template.md` — Ablauf bei
  Pull Requests.
* `.github/workflows/codeql.yml` — CodeQL laeuft nur, solange das Repository
  oeffentlich ist.

## Wo was liegt

```
protokoll_assistent_v2.py      Cloud-Variante, Konsole (reine Funktionen)
protokoll_assistent_gui.py     Cloud-Variante, tkinter-Fenster
setup_fenster.py               Einrichtungsfenster der Cloud-Variante
hauptanwendung.py              Startfenster, wählt zwischen beiden Varianten
oberflaeche_theme.py           gemeinsames tkinter-Erscheinungsbild

lokale_windows_app/
  app.py                       Einstiegspunkt (ruft zuerst bootstrap auf!)
  bootstrap.py                 legt bei Bedarf die Laufzeitumgebung an
  gui/                         PySide6: Hauptfenster, Assistent, Dialoge
  services/                    Verarbeitungskette, ohne Qt-Abhängigkeit
  utils/                       Pfade, Konfiguration, Diagnose, Logging

tests/                         Tests der Cloud-Variante
lokale_windows_app/tests/      Tests der lokalen Variante

protokoll_assistent_vereint/   dritte, vereinte Anwendung (siehe oben, in Aufbau)
  app.py                       Einstiegspunkt (Bootstrap nur im lokalen Modus)
  gui/                         PySide6: Hauptfenster, Einstellungsdialog, Worker
  services/                    API-Transkription/-Nachbearbeitung, Secret-Store
  utils/                       eigene Pfade/Konfiguration (qualifiziert importiert)
  tests/                       Tests der vereinten Anwendung
```

Die Verarbeitungskette in `services/` kennt kein Qt. Das soll so bleiben:
Oberfläche und Logik sind getrennt, deshalb sind die Dienste ohne Fenster
testbar.

`lokale_windows_app/app.py` ruft `bootstrap.ensure_runtime_and_relaunch()`
**vor** dem Import von PySide6 auf. Diese Reihenfolge ist zwingend — beim
allerersten Start ist PySide6 noch gar nicht installiert.
