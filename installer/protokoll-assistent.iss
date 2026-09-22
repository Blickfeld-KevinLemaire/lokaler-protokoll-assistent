; ---------------------------------------------------------------------------
; Inno-Setup-Skript fuer den Protokoll-Assistenten.
;
; Baut aus den beiden fertigen Build-Ergebnissen EINEN Installer:
;
;   ..\dist\Protokoll-Assistent\   die gebaute Anwendung,
;                                  erzeugt von 'protokoll_assistent.spec'
;   ..\protokoll_assistent\        dieselben Programmdateien als Quelltext -
;                                  fuer den lokalen Modus (siehe bootstrap.py)
;   ..\dist-python\python\         die mitgelieferte Python-Laufzeitumgebung,
;                                  geholt von 'python-laufzeit-holen.ps1'
;
; Der Anwender muss NICHTS vorinstallieren - auch kein Python. Im reinen
; API-Modus genuegt die eigenstaendige EXE; fuer den lokalen Modus liegt ein
; eigenes Python unter '{app}\python'.
;
; Die lokale Anwendung wird bewusst NICHT als EXE mitgeliefert: sie braucht
; PyTorch/WhisperX passend zur jeweiligen Grafikkarte (mehrere Gigabyte) und
; richtet sich diese Umgebung beim ersten Start selbst ein - mit dem
; mitgelieferten Python.
;
; Installiert wird ABSICHTLICH pro Benutzer (PrivilegesRequired=lowest, Ziel
; '%LOCALAPPDATA%\Programs\Protokoll-Assistent'):
;   * keine Administratorrechte noetig,
;   * der Programmordner bleibt beschreibbar. Das ist Pflicht, weil die
;     lokale Anwendung ihre Umgebung ('runtime\venv') und ihre Ausgabeordner
;     neben der Anwendung anlegt.
;
; Uebersetzen:  ISCC.exe /DMeineVersion=1.2.3 installer\protokoll-assistent.iss
; ---------------------------------------------------------------------------

#ifndef MeineVersion
  #define MeineVersion "0.0.0-entwicklung"
#endif

#define MeinName "Protokoll-Assistent"
#define MeinHersteller "Kevin Lemaire"
#define MeineUrl "https://github.com/Blickfeld-KevinLemaire/lokaler-protokoll-assistent"
#define MeineExe "Protokoll-Assistent.exe"

[Setup]
; Diese GUID identifiziert die Anwendung dauerhaft - bitte NICHT aendern,
; sonst erkennt ein neuer Installer eine vorhandene Installation nicht mehr
; und es entstehen zwei Eintraege in "Apps & Features".
AppId={{8E9A4C31-6B27-4F0E-9E64-6D0C2A5B7F11}
AppName={#MeinName}
AppVersion={#MeineVersion}
AppPublisher={#MeinHersteller}
AppPublisherURL={#MeineUrl}
AppSupportURL={#MeineUrl}/issues
AppUpdatesURL={#MeineUrl}/releases
DefaultDirName={autopf}\{#MeinName}
DefaultGroupName={#MeinName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
InfoAfterFile=hinweise-nach-installation.txt
OutputDir=..\dist-installer
OutputBaseFilename=Protokoll-Assistent-Setup-{#MeineVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Ohne Administratorrechte - siehe Kopfkommentar.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MeinName} {#MeineVersion}
UninstallDisplayIcon={app}\{#MeineExe}

[Languages]
Name: "deutsch"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 1) Die gebaute Anwendung als fertige EXE (mit gemeinsamem
;    '_internal'-Ordner, in dem die DLLs liegen).
; Die Ein-/Ausgabeordner entstehen erst beim Ausfuehren. Wurde die Anwendung
; vor dem Bauen des Installers lokal einmal gestartet, liegen sie im
; Build-Ordner - in den Installer gehoeren sie nicht. 'einstellungen' ist
; dabei besonders wichtig: dort steht 'fachbegriffe.txt' mit Projektnamen
; und echten Nachnamen (deshalb auch in '.gitignore').
;
; Ohne 'createallsubdirs', sonst wuerden diese Ordner wenigstens leer
; mitinstalliert. Alles, was wirklich gebraucht wird, enthaelt Dateien.
Source: "..\dist\Protokoll-Assistent\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs; \
    Excludes: "eingabe\*,ausgabe\*,zwischenstaende\*,einstellungen\*,Ergebnis des Meetings wie gew*"

; 2) Dieselben Programmdateien als Quelltext. Gebraucht werden sie nur im
;    lokalen Modus: Dort richtet 'bootstrap.py' eine eigene Umgebung mit
;    PyTorch/faster-whisper ein und startet die Anwendung darin neu.
;    Entwickler-, Test- und Laufzeitordner bleiben aussen vor.
; Ohne 'createallsubdirs': sonst wuerden die ausgeschlossenen Ordner
; (tests, __pycache__, ...) wenigstens leer mitinstalliert.
Source: "..\protokoll_assistent\*"; DestDir: "{app}\protokoll_assistent"; \
    Flags: ignoreversion recursesubdirs; \
    Excludes: "tests\*,__pycache__\*,*.pyc,runtime\*,logs\*,build\*,dist\*,dist-probe\*,.venv*\*,ausgabe\*"

; 3) Mitgelieferte Python-Laufzeitumgebung. Damit muss der Anwender kein
;    Python selbst installieren. Es ist ein eigenstaendiger Build von
;    'python-build-standalone'; er veraendert nichts am System und wird nur
;    aus diesem Ordner heraus verwendet. Eine bereits vorhandene
;    Python-Installation des Anwenders bleibt unberuehrt.
;    Vorher einmal 'installer\python-laufzeit-holen.ps1' ausfuehren.
Source: "..\dist-python\python\*"; DestDir: "{app}\python"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; 4) Lizenztexte sichtbar im Programmordner (LGPL-Pflicht, siehe NOTICES.md).
Source: "..\NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\lizenzen\*"; DestDir: "{app}\lizenzen"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MeinName}"; Filename: "{app}\{#MeineExe}"
Name: "{group}\{cm:UninstallProgram,{#MeinName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MeinName}"; Filename: "{app}\{#MeineExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MeineExe}"; Description: "{cm:LaunchProgram,{#MeinName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Die selbst eingerichtete Laufzeitumgebung und die Protokolldateien gehoeren
; zur Installation und wuerden sonst als mehrere Gigabyte zurueckbleiben.
; Ergebnisse des Anwenders ('ausgabe', 'Ergebnis des Meetings wie gewuenscht',
; 'einstellungen', 'zwischenstaende') werden ABSICHTLICH nicht geloescht.
Type: filesandordirs; Name: "{app}\protokoll_assistent\runtime"
Type: filesandordirs; Name: "{app}\protokoll_assistent\logs"
; Python legt beim Ausfuehren in JEDEM Paketordner ein '__pycache__' an.
; Inno kennt diese Dateien nicht (es hat sie nicht installiert) und wuerde
; sie stehen lassen - dann bliebe der Programmordner nach dem
; Deinstallieren zurueck. Kommt ein neuer Paketordner dazu, gehoert er
; hier ebenfalls hinein.
Type: filesandordirs; Name: "{app}\protokoll_assistent\__pycache__"
Type: filesandordirs; Name: "{app}\protokoll_assistent\gui\__pycache__"
Type: filesandordirs; Name: "{app}\protokoll_assistent\services\__pycache__"
Type: filesandordirs; Name: "{app}\protokoll_assistent\tools\__pycache__"
Type: filesandordirs; Name: "{app}\protokoll_assistent\utils\__pycache__"
; Dasselbe fuer die mitgelieferte Python-Laufzeitumgebung.
Type: filesandordirs; Name: "{app}\python"
