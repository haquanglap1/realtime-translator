# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for RealtimeTranslator.

Build:
    pyinstaller main.spec

Note: This creates a DIRECTORY distribution (not a single file),
because torch/CUDA/faster-whisper are too large and complex for
single-file mode.
"""

import sys
from pathlib import Path

block_cipher = None

# Detect if torch+CUDA is installed
try:
    import torch
    torch_path = Path(torch.__file__).parent
    has_torch = True
except ImportError:
    has_torch = False

# Detect faster_whisper / ctranslate2
try:
    import ctranslate2
    ct2_path = Path(ctranslate2.__file__).parent
    has_ct2 = True
except ImportError:
    has_ct2 = False

# Detect pyaudiowpatch
try:
    import pyaudiowpatch
    pa_path = Path(pyaudiowpatch.__file__).parent
    has_pa = True
except ImportError:
    has_pa = False


# --- Analysis ---

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Include config template (user copies to settings.yaml)
        ('config/settings.yaml.example', 'config'),
        ('config/prompts.yaml', 'config'),
    ],
    hiddenimports=[
        # Core
        'numpy',
        'sounddevice',
        'yaml',
        'openai',

        # faster-whisper
        'faster_whisper',
        'ctranslate2',
        'huggingface_hub',
        'tokenizers',

        # PyQt6
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.sip',

        # PyAudioWPatch
        'pyaudiowpatch',

        # Optional: pyannote (only if installed)
        # 'pyannote.audio',

        # Internal modules
        'core',
        'core.audio_capture',
        'core.vad',
        'core.transcriber',
        'core.translator',
        'core.pipeline',
        'core.diarizer',
        'ui',
        'ui.main_window',
        'ui.model_manager',
        'ui.stt_config',
        'ui.llm_config',
        'utils',
        'utils.config',
        'utils.ring_buffer',
        'utils.model_manager',
        'utils.torch_setup',
        'utils.stereo_mix',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy unused packages to reduce size
        'matplotlib',
        'scipy',
        'pandas',
        'notebook',
        'jupyter',
        'tkinter',
        'test',
        'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RealtimeTranslator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX can break torch/CUDA DLLs
    console=False,  # No console window (GUI app)
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
    name='RealtimeTranslator',
)
