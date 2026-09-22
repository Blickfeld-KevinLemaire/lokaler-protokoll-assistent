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
    "protokoll_assistent.services.api_protocol_service",
    "protokoll_assistent.services.api_transcription_service",
    "protokoll_assistent.services.chunking_service",
    "protokoll_assistent.services.diarization_service",
    "protokoll_assistent.services.environment_service",
    "protokoll_assistent.services.export_service",
    "protokoll_assistent.services.ffmpeg_service",
    "protokoll_assistent.services.manifest_service",
    "protokoll_assistent.services.merge_service",
    "protokoll_assistent.services.model_download_service",
    "protokoll_assistent.services.model_service",
    "protokoll_assistent.services.ollama_service",
    "protokoll_assistent.services.pipeline_service",
    "protokoll_assistent.services.protocol_service",
    "protokoll_assistent.services.recording_service",
    "protokoll_assistent.services.secret_store",
    "protokoll_assistent.services.speaker_merge_service",
    "protokoll_assistent.services.transcription_service",
    "protokoll_assistent.utils.app_config",
    "protokoll_assistent.utils.diagnostics",
    "protokoll_assistent.utils.hf_env",
    "protokoll_assistent.utils.json_validation",
    "protokoll_assistent.utils.logging_setup",
    "protokoll_assistent.utils.paths",
    "protokoll_assistent.utils.pyannote_patch",
    "protokoll_assistent.utils.setup_status",
    "protokoll_assistent.utils.systemprompt_vorlagen",
    "protokoll_assistent.utils.timeformat",
    "protokoll_assistent.gui.dialogs",
    "protokoll_assistent.gui.main_window",
    "protokoll_assistent.gui.settings_dialog",
    "protokoll_assistent.gui.strings",
    "protokoll_assistent.gui.theme",
    "protokoll_assistent.gui.wizard",
    "protokoll_assistent.gui.worker",
]


a = Analysis(
    ["protokoll_assistent/app.py"],
    # Damit "import protokoll_assistent.X" aufloesbar ist.
    pathex=["."],
    binaries=collected_binaries,
    datas=collected_datas
    + [
        ("protokoll_assistent/einstellungen", "einstellungen"),
        # Lizenzhinweise muessen mit ausgeliefert werden. Die LGPL-3.0 von Qt
        # verlangt, dass der Lizenztext beiliegt - die Qt-Wheels selbst
        # enthalten nur einen Verweis auf die kommerzielle Lizenz, nicht den
        # LGPL-Text. Siehe NOTICES.md im Projektstamm.
        ("NOTICES.md", "."),
        ("LICENSE", "."),
        ("lizenzen", "lizenzen"),
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

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Protokoll-Assistent",
)
