# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Spezifikation fuer den Dienst der neuen Oberflaeche (``vermerk-dienst.exe``).

Bauen:   uv run pyinstaller --noconfirm vermerk_dienst.spec
Ergebnis: dist/vermerk-dienst/vermerk-dienst.exe (+ _internal/)
Pruefen: uv run python tools/dienst_rauchtest.py dist/vermerk-dienst/vermerk-dienst.exe

Regeln (ARCHITEKTUR.md, CLAUDE.md Regel 7):
* NUR One-Directory (``exclude_binaries=True`` + ``COLLECT``). Ein One-File-Build entpackt sich bei jedem
  Start nach ``%TEMP%\_MEI...`` und liess nach jedem harten Abbruch hunderte MB dort liegen.
* ``upx=False``, ``strip=False``, ``optimize=0`` (asserts bleiben).
* Kein Qt: Das Fenster ist ``VERMERK.exe`` (Tauri, ``oberflaeche/src-tauri``); die alte Qt-Oberflaeche ist entfernt.
* Kein Torch/faster-whisper/pyannote: Die schwere Rechenumgebung richtet ``bootstrap.py`` im lokalen Modus
  bei Bedarf selbst ein (mit dem mitgelieferten Python aus dem Installer) und startet den Dienst dort aus
  dem Quelltext neu.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

hiddenimports = []
for paket in ("uvicorn", "fastapi", "starlette", "pydantic", "pydantic_core", "multipart", "python_multipart"):
    try:
        hiddenimports += collect_submodules(paket, filter=lambda name: name != "pydantic.mypy")
    except Exception:  # noqa: BLE001 -- nicht jedes Paket gibt es unter beiden Namen
        pass
hiddenimports += [
    "anyio._backends._asyncio",
    "h11",
    "reportlab.graphics.barcode.common",
    "reportlab.graphics.barcode.code128",
    "reportlab.graphics.barcode.code39",
    "reportlab.graphics.barcode.code93",
    "reportlab.graphics.barcode.usps",
    "reportlab.graphics.barcode.usps4s",
    "reportlab.graphics.barcode.ecc200datamatrix",
    "reportlab.graphics.barcode.qr",
    "reportlab.pdfbase._fontdata",
    # Wird per importlib.util.find_spec abgefragt bzw. erst bei Bedarf importiert.
    "sounddevice",
    "keyring.backends.Windows",
]
hiddenimports += collect_submodules("reportlab.pdfbase")
hiddenimports += collect_submodules("protokoll_assistent", filter=lambda name: ".tests" not in name)

datas = [
    ("protokoll_assistent/resources", "resources"),
    ("protokoll_assistent/einstellungen", "einstellungen"),
    # Die Paketlisten liest 'bootstrap.py' fuer die Rechenumgebung des lokalen Modus.
    ("protokoll_assistent/requirements-anwendung.txt", "protokoll_assistent"),
    ("protokoll_assistent/requirements-laufzeit.txt", "protokoll_assistent"),
    ("protokoll_assistent/requirements-torch.txt", "protokoll_assistent"),
    ("protokoll_assistent/requirements-server.txt", "protokoll_assistent"),
    ("NOTICES.md", "."),
    ("LICENSE", "."),
    ("lizenzen", "lizenzen"),
]
datas += collect_data_files("reportlab")
for paket in ("_sounddevice_data",):
    try:
        datas += collect_data_files(paket)
    except Exception:  # noqa: BLE001
        pass
# Die gebaute Oberflaeche: Der Dienst liefert sie an Browser aus ('oberflaeche_ordner()' sucht in
# 'sys._MEIPASS/oberflaeche'). Fehlt der Build, laeuft der Dienst trotzdem (nur ohne Browser-Oberflaeche).
if (Path("oberflaeche") / "build" / "index.html").is_file():
    datas.append(("oberflaeche/build", "oberflaeche"))
else:
    print("HINWEIS: oberflaeche/build fehlt -- der Dienst wird ohne Browser-Oberflaeche gebaut.")

a = Analysis(
    ["vermerk_dienst.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "_pytest",
        "protokoll_assistent.tests",
        "torch",
        "torchaudio",
        "faster_whisper",
        "ctranslate2",
        "pyannote",
        "whisperx",
        # 'collect_submodules("pydantic")' zoege sonst das mypy-Plugin und damit mypy selbst mit.
        "pydantic.mypy",
        "mypy",
    ],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="vermerk-dienst",
    icon="protokoll_assistent/resources/vermerk_icon.ico",
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

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="vermerk-dienst",
)
