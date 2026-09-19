# Installer bauen

Hier liegt das Inno-Setup-Skript, aus dem
`Protokoll-Assistent-Setup-<Version>.exe` entsteht.

Normalerweise muss das niemand von Hand machen: Die GitHub-Ablaeufe bauen
den Installer automatisch (siehe unten). Diese Anleitung ist fuer den Fall,
dass man das Ergebnis lokal ausprobieren will.

## Was drin landet

| Bestandteil | Form | Woher |
|---|---|---|
| Auswahlfenster (`hauptanwendung.py`) | `Protokoll-Assistent.exe` | PyInstaller, `../protokoll_assistent_cloud.spec` |
| Cloud-Variante (`protokoll_assistent_gui.py`) | `Protokoll-Assistent-Cloud.exe` | dieselbe Spezifikation, gemeinsamer `_internal`-Ordner |
| Vollstaendig lokale Anwendung | Programmdateien | `../lokale_windows_app/` (ohne `tests`, `runtime`, `logs`, `__pycache__`) |
| Lizenztexte | `LICENSE`, `NOTICES.md`, `lizenzen/` | Projektstamm |

Die lokale Anwendung wird **nicht** als EXE mitgeliefert. Sie braucht
PyTorch/WhisperX passend zur jeweiligen Grafikkarte - mehrere Gigabyte, je
nach Rechner verschieden. Sie richtet sich diese Umgebung beim ersten Start
wie bisher selbst ein (`lokale_windows_app/bootstrap.py`) und braucht dafuer
ein installiertes Python 3.10/3.11. Findet das Auswahlfenster keines,
erklaert es das und verweist auf python.org. Die Cloud-Variante laeuft ohne
Python.

## Selbst bauen

```powershell
# 1. Inno Setup (einmalig)
winget install --exact --id JRSoftware.InnoSetup --scope user

# 2. Die beiden EXEs bauen (im Projektstamm)
uv run pyinstaller --noconfirm protokoll_assistent_cloud.spec

# 3. Installer uebersetzen
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
* **`einstellungen` ist ausgeschlossen.** Dort steht `fachbegriffe.txt` mit
  Projektnamen und echten Nachnamen - die Datei ist aus gutem Grund auch in
  `.gitignore` und darf nicht in einen Installer geraten, nur weil jemand
  die Anwendung vor dem Bauen einmal gestartet hat.
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
