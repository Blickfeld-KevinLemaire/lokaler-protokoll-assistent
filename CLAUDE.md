# Hinweise für Claude Code

Diese Datei wird bei jeder Sitzung automatisch geladen. Sie hält fest, worauf
in diesem Projekt geachtet werden muss — inklusive der Gründe, damit klar ist,
wann eine Regel greift und wann nicht.

## Was das Projekt ist

Zwei eigenständige Anwendungen, die sich nichts teilen außer der Sprache:

| | Ordner | Technik |
|---|---|---|
| Cloud-Variante | Projektwurzel (`protokoll_assistent_gui.py`, `protokoll_assistent_v2.py`) | tkinter, Transkription über einen frei wählbaren API-Endpunkt |
| Lokale Variante | `lokale_windows_app/` | PySide6, WhisperX + pyannote + Ollama, vollständig offline |

Beide werden aktiv gepflegt. Die lokale Variante ist **kein** Nachfolger der
Cloud-Variante — wer keine Daten aus der Hand geben will, nimmt die lokale;
wer keine KI-Modelle installieren will, die Cloud-Variante.

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

PyTorch, WhisperX und pyannote leben in `.venv-whisperx` und stehen
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

### 7. Die Installation der Anwender nicht anfassen

`Protokoll-Assistent-Einrichten.bat`, `lokale_windows_app/setup_lokal.ps1`,
`requirements.txt` und `requirements-local-gui.txt` sind der Weg, auf dem
Anwender die Anwendung installieren. `pyproject.toml` steht **zusätzlich**
daneben und gilt nur für Entwicklung und CI. Neue Laufzeit-Abhängigkeiten
gehören in beide, sonst fehlen sie den Anwendern.

### 8. Bestehendes nicht umbenennen oder durchformatieren

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

### 9. Die CI kostet Geld

Privates Repository auf einem kostenlosen Konto: 2000 Minuten im Monat, und
**Windows-Läufer zählen doppelt**. Deshalb laufen Linting, Typprüfung und die
Sicherheitsprüfungen auf Linux, ein neuer Push bricht den vorherigen Lauf ab,
und der nächtliche Build fällt aus, wenn es keine neuen Commits gab.

Keine zusätzlichen Windows-Jobs ohne Not. CodeQL und die Geheimnis-Erkennung
von GitHub sind auf diesem Tarif nicht verfügbar — diese Aufgabe übernehmen
gitleaks, die `S`-Regeln von ruff und pip-audit.

`ci.yml` läuft bei jedem Push auf **jeden** Branch, damit ein Stand schon
geprüft ist, bevor daraus ein Pull Request wird. Damit ein Branch mit offenem
Pull Request nicht doppelt geprüft wird, ist die `concurrency`-Gruppe auf den
Branchnamen geschlüsselt — nicht auf `github.ref`. Diese Gruppe bitte so
lassen.

**Die CI kann melden, aber nicht blockieren.** Erforderliche Statusprüfungen
(„required status checks") sind Teil der Branch-Schutzregeln, und die gibt es
für ein privates Repository auf einem kostenlosen Konto nicht. Ein roter Lauf
verhindert das Zusammenführen also nicht automatisch — vor dem Merge selbst
nachsehen.

## Weitere Dateien, die mitgepflegt werden wollen

* `SECURITY.md` — was in diesem Projekt sicherheitsrelevant ist und wie man
  eine Luecke meldet. Bei Aenderungen an der Datenuebertragung oder an den
  ausgeschlossenen Ordnern bitte dort nachziehen.
* `LICENSE` — der Quelltext ist oeffentlich lesbar, aber **nicht** zur Nutzung
  freigegeben. Keine Lizenzhinweise entfernen.
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
```

Die Verarbeitungskette in `services/` kennt kein Qt. Das soll so bleiben:
Oberfläche und Logik sind getrennt, deshalb sind die Dienste ohne Fenster
testbar.

`lokale_windows_app/app.py` ruft `bootstrap.ensure_runtime_and_relaunch()`
**vor** dem Import von PySide6 auf. Diese Reihenfolge ist zwingend — beim
allerersten Start ist PySide6 noch gar nicht installiert.
