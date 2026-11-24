; ---------------------------------------------------------------------------
; Inno-Setup-Skript fuer VERMERK Desktop.
;
; Baut aus den fertigen Build-Ergebnissen EINEN Installer:
;
;   ..\oberflaeche\src-tauri\target\release\VERMERK.exe
;                                  das Fenster (Tauri 2, siehe ARCHITEKTUR.md),
;                                  -> {app}\VERMERK.exe
;   ..\dist\vermerk-dienst\       der Dienst (One-Directory, erzeugt von
;                                  'vermerk_dienst.spec') -> {app}\dienst\
;   ..\protokoll_assistent\        die Programmdateien als Quelltext -
;                                  fuer den lokalen Modus (siehe bootstrap.py)
;   ..\dist-python\python\         die mitgelieferte Python-Laufzeitumgebung,
;                                  geholt von 'python-laufzeit-holen.ps1'
;
; Der Anwender muss NICHTS vorinstallieren - auch kein Python. Im reinen
; API-Modus genuegen Fenster und Dienst; fuer den lokalen Modus liegt ein
; eigenes Python unter '{app}\python'. Das Fenster braucht Microsoft Edge
; WebView2 - unter Windows 10/11 ist es vorinstalliert und wird nicht
; mitgeliefert.
;
; Einstellungen und Daten liegen weiter in '{app}' (nicht in '{app}\dienst'):
; Das Fenster gibt dem Dienst seinen Ordner ueber VERMERK_ANWENDUNGSORDNER mit.
;
; Die lokale Anwendung wird bewusst NICHT als EXE mitgeliefert: sie braucht
; PyTorch/WhisperX passend zur jeweiligen Grafikkarte (mehrere Gigabyte) und
; richtet sich diese Umgebung beim ersten Start selbst ein - mit dem
; mitgelieferten Python.
;
; Installiert wird ABSICHTLICH pro Benutzer (PrivilegesRequired=lowest, Ziel
; '%LOCALAPPDATA%\Programs\VERMERK Desktop'):
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

#define MeinName "VERMERK Desktop"
#define MeinHersteller "Kevin Lemaire"
#define MeineUrl "https://github.com/Blickfeld-KevinLemaire/lokaler-protokoll-assistent"
#define MeineExe "VERMERK.exe"

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
OutputBaseFilename=VERMERK-Desktop-Setup-{#MeineVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Ohne Administratorrechte - siehe Kopfkommentar.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MeinName} {#MeineVersion}
UninstallDisplayIcon={app}\{#MeineExe}
SetupIconFile=..\protokoll_assistent\resources\vermerk_icon.ico

[Languages]
Name: "deutsch"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 1) Das Fenster.
Source: "..\oberflaeche\src-tauri\target\release\VERMERK.exe"; DestDir: "{app}"; Flags: ignoreversion

; 1b) Der Dienst (mit eigenem '_internal'-Ordner, in dem die DLLs liegen).
; Die Ein-/Ausgabeordner entstehen erst beim Ausfuehren. Wurde der Dienst vor
; dem Bauen des Installers gestartet (Rauchtest), koennen sie im Build-Ordner
; liegen - in den Installer gehoeren sie nicht. 'einstellungen' ist dabei
; besonders wichtig: dort steht 'fachbegriffe.txt' mit Projektnamen und echten
; Nachnamen. Die Muster beginnen mit '\', gelten also nur fuer die oberste
; Ebene - '_internal\einstellungen' (die mitgelieferte Vorlage) bleibt.
;
; Ohne 'createallsubdirs', sonst wuerden diese Ordner wenigstens leer
; mitinstalliert. Alles, was wirklich gebraucht wird, enthaelt Dateien.
Source: "..\dist\vermerk-dienst\*"; DestDir: "{app}\dienst"; \
    Flags: ignoreversion recursesubdirs; \
    Excludes: "\eingabe\*,\ausgabe\*,\aufnahmen\*,\arbeitsdaten\*,\logs\*,\sprecherprofile\*,\chatverlaeufe\*,\zwischenstaende\*,\einstellungen\*,\konfiguration.json,\Ergebnis des Meetings wie gew*"

; 2) Dieselben Programmdateien als Quelltext. Gebraucht werden sie nur im
;    lokalen Modus: Dort richtet 'bootstrap.py' eine eigene Umgebung mit
;    PyTorch/faster-whisper ein und startet den Dienst darin neu.
;    Entwickler-, Test- und Laufzeitordner bleiben aussen vor.
; Ohne 'createallsubdirs': sonst wuerden die ausgeschlossenen Ordner
; (tests, __pycache__, ...) wenigstens leer mitinstalliert.
Source: "..\protokoll_assistent\*"; DestDir: "{app}\protokoll_assistent"; \
    Flags: ignoreversion recursesubdirs; \
    Excludes: "tests\*,__pycache__\*,*.pyc,runtime\*,logs\*,build\*,dist\*,dist-probe\*,.venv*\*,ausgabe\*,sprecherprofile\*,chatverlaeufe\*,aufnahmen\*,arbeitsdaten\*,konfiguration.json,konfiguration.defekt.json,Einrichtungsstatus.json,.pytest_cache\*,tools\ffmpeg\*,einstellungen\systemprompt_protokoll.txt,einstellungen\systemprompt_vorlagen\*,einstellungen\fachbegriffe.txt"
; Zu den Ausschluessen oben:
; * 'einstellungen\systemprompt_protokoll.txt' ist der Auftrag des ANWENDERS. Im Repository liegt die
;   Datei leer; mit installiert, ueberschrieb jedes Update den selbst geschriebenen Auftrag einer
;   Installation, die ihre Daten noch im Unterordner fuehrt (bis 0.5.0-beta der Normalfall im lokalen
;   Modus). Fehlt sie, legt die Anwendung sie beim Start aus der '.default.txt' an.
; * 'aufnahmen', 'arbeitsdaten', 'konfiguration.json', 'tools\ffmpeg' entstehen erst beim Benutzen. Bei
;   einem Build aus einem benutzten Arbeitsordner kaemen sonst eigene Aufnahmen, Einstellungen und ein
;   heruntergeladenes FFmpeg (GPL) in den Installer.

; 3) Mitgelieferte Python-Laufzeitumgebung. Damit muss der Anwender kein
;    Python selbst installieren. Es ist ein eigenstaendiger Build von
;    'python-build-standalone'; er veraendert nichts am System und wird nur
;    aus diesem Ordner heraus verwendet. Eine bereits vorhandene
;    Python-Installation des Anwenders bleibt unberuehrt.
;    Vorher einmal 'installer\python-laufzeit-holen.ps1' ausfuehren.
Source: "..\dist-python\python\*"; DestDir: "{app}\python"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; 4) Lizenztexte und Urheberhinweise sichtbar im Programmordner (siehe NOTICES.md).
Source: "..\NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\lizenzen\*"; DestDir: "{app}\lizenzen"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MeinName}"; Filename: "{app}\{#MeineExe}"
Name: "{group}\{cm:UninstallProgram,{#MeinName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MeinName}"; Filename: "{app}\{#MeineExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MeineExe}"; Description: "{cm:LaunchProgram,{#MeinName}}"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; Reste des alten Namens "Protokoll-Assistent" (bis 0.4.0-rc12). Ein Update
; landet wegen derselben AppId im alten Programmordner - dort bliebe die alte
; EXE neben der neuen liegen, und die alten Verknuepfungen im Startmenue und
; auf dem Desktop starteten weiter sie: also die ALTE Programmfassung, nur mit
; den neuen Bibliotheken aus '_internal'. Fehlt eine Datei, passiert nichts.
Type: files; Name: "{app}\Protokoll-Assistent.exe"
Type: files; Name: "{group}\Protokoll-Assistent.lnk"
Type: files; Name: "{group}\{cm:UninstallProgram,Protokoll-Assistent}.lnk"
Type: files; Name: "{autodesktop}\Protokoll-Assistent.lnk"
; Das alte Qt-Fenster (bis 0.5.x): 'VERMERK-Desktop.exe' mit seinem Ordner
; '_internal' direkt im Programmordner. Seit 0.6.0 startet 'VERMERK.exe'; der
; Dienst hat seine Bibliotheken in 'dienst\_internal'. Die Verknuepfungen
; tragen denselben Namen und zeigen nach dem Update auf 'VERMERK.exe'.
; Einstellungen und Daten liegen nicht in '_internal' und bleiben erhalten.
Type: files; Name: "{app}\VERMERK-Desktop.exe"
Type: filesandordirs; Name: "{app}\_internal"
; Der Quelltext der alten Qt-Oberflaeche und ihre Startskripte (bis 0.6.0-alpha.1 mitinstalliert). Inno
; entfernt Dateien, die eine neue Fassung nicht mehr mitbringt, beim Update nicht von selbst.
Type: filesandordirs; Name: "{app}\protokoll_assistent\gui"
Type: files; Name: "{app}\protokoll_assistent\app.py"
Type: files; Name: "{app}\protokoll_assistent\Start-Protokoll-Assistent.ps1"
Type: files; Name: "{app}\protokoll_assistent\start_lokal.ps1"
Type: files; Name: "{app}\protokoll_assistent\Anwendung-starten.ps1"
Type: files; Name: "{app}\protokoll_assistent\build_windows.ps1"

[UninstallDelete]
; Die selbst eingerichtete Laufzeitumgebung und die Protokolldateien gehoeren
; zur Installation und wuerden sonst als mehrere Gigabyte zurueckbleiben.
; Ergebnisse des Anwenders ('ausgabe', 'Ergebnis des Meetings wie gewuenscht',
; 'einstellungen', 'zwischenstaende') werden ABSICHTLICH nicht geloescht.
Type: filesandordirs; Name: "{app}\protokoll_assistent\runtime"
Type: filesandordirs; Name: "{app}\protokoll_assistent\logs"
; Die gebaute EXE legt beides DIREKT im Programmordner an ('runtime\venv' mit gut 5 GB, dazu der geladene
; Ollama-Installer und FFmpeg). Bis 0.5.0-beta stand hier nur der Unterordner oben -- die eigentliche
; Rechenumgebung blieb nach dem Deinstallieren zurueck.
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\tools\ffmpeg"
Type: filesandordirs; Name: "{app}\protokoll_assistent\tools\ffmpeg"
; Python legt beim Ausfuehren in JEDEM Paketordner ein '__pycache__' an.
; Inno kennt diese Dateien nicht (es hat sie nicht installiert) und wuerde
; sie stehen lassen - dann bliebe der Programmordner nach dem
; Deinstallieren zurueck. Kommt ein neuer Paketordner dazu, gehoert er
; hier ebenfalls hinein.
Type: filesandordirs; Name: "{app}\protokoll_assistent\__pycache__"
Type: filesandordirs; Name: "{app}\protokoll_assistent\services\__pycache__"
Type: filesandordirs; Name: "{app}\protokoll_assistent\tools\__pycache__"
Type: filesandordirs; Name: "{app}\protokoll_assistent\utils\__pycache__"
Type: filesandordirs; Name: "{app}\protokoll_assistent\server\__pycache__"
Type: filesandordirs; Name: "{app}\protokoll_assistent\api\__pycache__"
Type: filesandordirs; Name: "{app}\protokoll_assistent\ablauf\__pycache__"
; Protokolle des Dienstes, falls er sie neben sich anlegt.
Type: filesandordirs; Name: "{app}\dienst\logs"
; Dasselbe fuer die mitgelieferte Python-Laufzeitumgebung.
Type: filesandordirs; Name: "{app}\python"
; Das Fenster (Tauri) fuehrt seine Protokolle ('logs': vermerk-*.log, dienst.log), die Handschlag-Dateien
; ('laufzeit') und den Speicher von WebView2 ('EBWebView') unter %LOCALAPPDATA%\<identifier> -- nicht im
; Programmordner. Bisher blieb der Ordner nach dem Deinstallieren liegen, obwohl die Hinweise sagen, die
; Protokolldateien wuerden entfernt. Darin liegen keine Ergebnisse und keine 'konfiguration.json' -- nur
; das im Fenster gewaehlte Farbschema geht mit.
; Der Name muss zu "identifier" in oberflaeche\src-tauri\tauri.conf.json passen (ein Test prueft das).
Type: filesandordirs; Name: "{localappdata}\de.vermerk.desktop"
