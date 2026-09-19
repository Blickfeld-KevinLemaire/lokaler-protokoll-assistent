# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Spezifikation fuer Protokoll-Assistent Lokal.

One-Directory-Build (kein One-File), da WhisperX/PyTorch/CUDA fuer einen
One-File-Build ungeeignet gross sind und das Entpacken bei jedem Start
unnoetig verlangsamen wuerden.

WICHTIG:
* Modelldateien (Hugging-Face-/Ollama-Cache) werden NICHT in den Build
  kopiert. Die gebaute Anwendung verwendet weiterhin den vorhandenen Cache
  auf dem jeweiligen Rechner.
* Dieses Spec-File konnte in der Entwicklungsumgebung nur mit installiertem
  PySide6/PyInstaller, aber OHNE WhisperX/PyTorch/pyannote (dort nicht
  installierbar, siehe README.md) probeweise ausgefuehrt werden. Auf Ihrem
  Windows-Rechner mit vollstaendiger '.venv-whisperx' werden die unten
  gelisteten Pakete automatisch mit allen Daten/Submodulen eingesammelt.
  Meldet PyInstaller dennoch 'ModuleNotFoundError', ergaenzen Sie das
  fehlende Paket einfach in der Liste ``PACKAGES_TO_COLLECT`` unten.
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

PACKAGES_TO_COLLECT = (
    "whisperx",
    "pyannote",
    "speechbrain",
    "lightning",
    "lightning_fabric",
    "asteroid_filterbanks",
    "torchaudio",
    "torch",
    "transformers",
    "huggingface_hub",
    "ctranslate2",
    "faster_whisper",
)

collected_datas = []
collected_binaries = []
collected_hiddenimports = []

for package_name in PACKAGES_TO_COLLECT:
    try:
        datas, binaries, hiddenimports = collect_all(package_name)
    except Exception:
        # Paket ist in dieser Build-Umgebung nicht installiert/auffindbar.
        # Auf dem Ziel-Windows-Rechner mit vollstaendiger .venv-whisperx
        # sind alle oben gelisteten Pakete vorhanden.
        continue
    collected_datas += datas
    collected_binaries += binaries
    collected_hiddenimports += hiddenimports

collected_hiddenimports += collect_submodules("PySide6")
collected_hiddenimports += [
    "services.chunking_service",
    "services.diarization_service",
    "services.environment_service",
    "services.export_service",
    "services.ffmpeg_service",
    "services.manifest_service",
    "services.merge_service",
    "services.model_download_service",
    "services.model_service",
    "services.ollama_service",
    "services.pipeline_service",
    "services.protocol_service",
    "services.speaker_merge_service",
    "services.transcription_service",
    "utils.app_config",
    "utils.diagnostics",
    "utils.hf_env",
    "utils.json_validation",
    "utils.logging_setup",
    "utils.paths",
    "utils.pyannote_patch",
    "utils.setup_status",
    "utils.timeformat",
    "gui.dialogs",
    "gui.main_window",
    "gui.strings",
    "gui.theme",
    "gui.wizard",
    "gui.worker",
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=collected_binaries,
    datas=collected_datas
    + [
        ("einstellungen", "einstellungen"),
        # Lizenzhinweise muessen mit ausgeliefert werden. Die LGPL-3.0 von Qt
        # verlangt, dass der Lizenztext beiliegt - die Qt-Wheels selbst
        # enthalten nur einen Verweis auf die kommerzielle Lizenz, nicht den
        # LGPL-Text. Siehe NOTICES.md im Projektstamm.
        ("../NOTICES.md", "."),
        ("../LICENSE", "."),
        ("../lizenzen", "lizenzen"),
    ],
    hiddenimports=collected_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Protokoll-Assistent-Lokal",
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
    name="Protokoll-Assistent-Lokal",
)
