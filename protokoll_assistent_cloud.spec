# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Spezifikation fuer das Auswahlfenster und die Cloud-Variante.

Ergebnis ist ein One-Directory-Build mit ZWEI Programmen, die sich einen
gemeinsamen '_internal'-Ordner teilen:

    Protokoll-Assistent.exe         <- hauptanwendung.py (Auswahlfenster)
    Protokoll-Assistent-Cloud.exe   <- protokoll_assistent_gui.py

Beide brauchen ausser 'tkinter' und dem optionalen 'sv_ttk' nichts, was nicht
in der Standardbibliothek steht -- diese EXEs sind deshalb vollstaendig
eigenstaendig und brauchen KEIN Python auf dem Zielrechner.

Die vollstaendig lokale Anwendung ('lokale_windows_app/') wird hier bewusst
NICHT gebaut: sie braucht PyTorch/WhisperX, die je nach Grafikkarte
unterschiedlich sind und mehrere Gigabyte gross waeren. Sie wird vom
Installer als Programmdateien mitgeliefert und richtet sich beim ersten
Start wie bisher selbst ein (siehe 'lokale_windows_app/bootstrap.py').

Aufruf:  pyinstaller --noconfirm protokoll_assistent_cloud.spec
"""

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# 'sv_ttk' ist optional (siehe requirements.txt). Fehlt es in der
# Build-Umgebung, laufen beide Programme mit dem schlichteren Standard-Design
# weiter -- der Build soll daran nicht scheitern.
sv_ttk_datas: list = []
sv_ttk_binaries: list = []
sv_ttk_hiddenimports: list = []
try:
    sv_ttk_datas, sv_ttk_binaries, sv_ttk_hiddenimports = collect_all("sv_ttk")
except Exception:
    pass

# Lizenzhinweise muessen mit ausgeliefert werden (siehe NOTICES.md).
LIZENZ_DATEN = [
    ("NOTICES.md", "."),
    ("LICENSE", "."),
    ("lizenzen", "lizenzen"),
]

GEMEINSAME_IMPORTE = [
    "oberflaeche_theme",
    "protokoll_assistent_v2",
    *sv_ttk_hiddenimports,
]

a_auswahl = Analysis(
    ["hauptanwendung.py"],
    pathex=["."],
    binaries=sv_ttk_binaries,
    datas=sv_ttk_datas + LIZENZ_DATEN,
    hiddenimports=GEMEINSAME_IMPORTE,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

a_cloud = Analysis(
    ["protokoll_assistent_gui.py"],
    pathex=["."],
    binaries=sv_ttk_binaries,
    datas=sv_ttk_datas + LIZENZ_DATEN,
    hiddenimports=GEMEINSAME_IMPORTE,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz_auswahl = PYZ(a_auswahl.pure, a_auswahl.zipped_data, cipher=block_cipher)
pyz_cloud = PYZ(a_cloud.pure, a_cloud.zipped_data, cipher=block_cipher)

exe_auswahl = EXE(
    pyz_auswahl,
    a_auswahl.scripts,
    [],
    exclude_binaries=True,
    name="Protokoll-Assistent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

exe_cloud = EXE(
    pyz_cloud,
    a_cloud.scripts,
    [],
    exclude_binaries=True,
    name="Protokoll-Assistent-Cloud",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Ein gemeinsames COLLECT: doppelte Dateien werden dabei nur einmal abgelegt,
# beide EXEs benutzen denselben '_internal'-Ordner.
coll = COLLECT(
    exe_auswahl,
    a_auswahl.binaries,
    a_auswahl.zipfiles,
    a_auswahl.datas,
    exe_cloud,
    a_cloud.binaries,
    a_cloud.zipfiles,
    a_cloud.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Protokoll-Assistent",
)
