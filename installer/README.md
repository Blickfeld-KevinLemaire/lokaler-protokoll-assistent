# Installer bauen

Hier liegt das Inno-Setup-Skript, aus dem
`Protokoll-Assistent-Setup-<Version>.exe` entsteht.

Normalerweise muss das niemand von Hand machen: Die GitHub-Ablaeufe bauen
den Installer automatisch (siehe unten). Diese Anleitung ist fuer den Fall,
dass man das Ergebnis lokal ausprobieren will.

## Was drin landet

| Bestandteil | Form | Woher |
|---|---|---|
| Die Anwendung | `Protokoll-Assistent.exe` | PyInstaller, `../protokoll_assistent.spec` |
| Dieselbe Anwendung als Quelltext | Programmdateien | `../protokoll_assistent/` (ohne `tests`, `runtime`, `logs`, `__pycache__`) |
| Python-Laufzeitumgebung | `python\` (CPython 3.11) | `python-laufzeit-holen.ps1` |
| Lizenztexte | `LICENSE`, `NOTICES.md`, `lizenzen/` | Projektstamm |

**Warum zweimal dasselbe?** Die EXE genuegt fuer den API-Modus. Der lokale
Modus braucht PyTorch/faster-whisper passend zur jeweiligen Grafikkarte -
mehrere Gigabyte, je nach Rechner verschieden; das laesst sich nicht sinnvoll
buendeln. Dafuer richtet sich die Anwendung beim ersten Start aus dem
mitgelieferten Quelltext heraus selbst eine Umgebung ein
(`protokoll_assistent/bootstrap.py`).

**Der Anwender muss dafuer kein Python installieren.** Der Installer bringt
unter `{app}\python` eine eigene Laufzeitumgebung mit. Nur wenn dieser Ordner
fehlt, wird ersatzweise nach einem installierten Python 3.10/3.11 gesucht.

`bootstrap.py` musste dafuer **nicht** angefasst werden: es nimmt ohnehin
das Python entgegen, mit dem es gestartet wurde, und baut daraus
`runtime\venv`.

## Selbst bauen

```powershell
# 1. Inno Setup (einmalig)
winget install --exact --id JRSoftware.InnoSetup --scope user

# 2. Die beiden EXEs bauen (im Projektstamm)
uv run pyinstaller --noconfirm protokoll_assistent.spec

# 3. Python-Laufzeitumgebung holen (~24 MB Download, einmalig)
pwsh -NoProfile -File installer\python-laufzeit-holen.ps1

# 4. Installer uebersetzen
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" `
    /DMeineVersion=0.0.0-test installer\protokoll-assistent.iss
```

Das Ergebnis liegt in `..\dist-installer\` (nicht im Repository, siehe
`.gitignore`).

Zum Ausprobieren ohne Klickstrecke:

```powershell
.\dist-installer\Protokoll-Assistent-Setup-0.0.0-test.exe `
    /VERYSILENT /SUPPRESSMSGBOXES /NOICONS /DIR=C:\Temp\PA-Test
C:\Temp\PA-Test\unins000.exe /VERYSILENT   # wieder entfernen
```

## Entscheidungen, die im Skript stecken

* **Installation pro Benutzer** (`PrivilegesRequired=lowest`, Ziel
  `%LOCALAPPDATA%\Programs\Protokoll-Assistent`). Zwei Gruende: keine
  Administratorrechte noetig, und der Programmordner bleibt beschreibbar -
  das ist Pflicht, weil die lokale Anwendung ihre Umgebung (`runtime\venv`)
  und ihre Ausgabeordner neben der Anwendung anlegt. Unter
  `C:\Program Files` wuerde das scheitern.
* **Kein `createallsubdirs`.** Sonst legt Inno auch die ausgeschlossenen
  Ordner (`tests`, `__pycache__`, `eingabe`, ...) wenigstens leer an.
* **Laufzeitordner sind ausgeschlossen** (`ausgabe`, `aufnahmen`,
  `arbeitsdaten`, `runtime`, `logs`). Sie duerfen nicht in einen Installer
  geraten, nur weil jemand die Anwendung vor dem Bauen einmal gestartet hat.
* **Die Python-Laufzeitumgebung ist fest eingetragen** (Version und
  SHA256-Pruefsumme in `python-laufzeit-holen.ps1`). Ein Build soll immer
  dasselbe Ergebnis liefern, und eine Laufzeitumgebung aus dem Netz wird nur
  verwendet, wenn ihre Pruefsumme stimmt. Beim Aktualisieren beides
  zusammen aendern - die Pruefsumme steht in der Datei `SHA256SUMS` der
  jeweiligen Veroeffentlichung.
* **Die `AppId` darf sich nie aendern.** An ihr erkennt ein neuer Installer
  eine vorhandene Installation. Mit einer neuen GUID entstuenden zwei
  Eintraege in "Apps & Features".
* **Beim Deinstallieren** werden `runtime` und `logs` mit entfernt (sonst
  bleiben mehrere Gigabyte liegen), die Ergebnisordner des Anwenders
  dagegen absichtlich nicht.

## Wo der Installer automatisch gebaut wird

* [`.github/workflows/release.yml`](../.github/workflows/release.yml) - bei
  einem Tag `v*`. Haengt den Installer an das GitHub-Release.
* [`.github/workflows/nightly.yml`](../.github/workflows/nightly.yml) - jede
  Nacht, wenn es neue Commits gab. Legt den Installer als Artefakt des Laufs
  ab (14 Tage), bewusst **nicht** als Release: dieser Build ist von
  niemandem ausprobiert worden.

## Nicht geloest: Signatur

Der Installer ist nicht signiert, deshalb meldet sich Windows SmartScreen.
Daran aendert kein Installer-Format etwas - dafuer braucht es ein
Code-Signing-Zertifikat. Fuer Open-Source-Projekte gibt es das kostenlos
ueber <https://signpath.io>.
