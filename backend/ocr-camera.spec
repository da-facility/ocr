# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for OCR Camera App.

Build with:
    uv run pyinstaller ocr-camera.spec --noconfirm --distpath ../dist

Environment variables:
    RELEASE_BUILD=1  - Enable UPX compression (smaller but slower build)
    OUTPUT_NAME=name - Set output executable name (default: OCR-Camera)

Prerequisites:
    1. Build frontend first: cd ../frontend && bun run build
    2. Backend deps installed: uv sync
"""

import os
import sys
from pathlib import Path

# Build mode: release enables UPX compression
is_release = os.environ.get('RELEASE_BUILD', '0') == '1'

# Output name (without extension)
output_name = os.environ.get('OUTPUT_NAME', 'OCR-Camera')

# Paths
backend_dir = Path(SPECPATH)
frontend_dist = backend_dir.parent / 'frontend' / 'dist'

# Check if frontend is built
if not frontend_dist.exists():
    print("ERROR: Frontend not built! Run 'bun run build' in frontend/ first.")
    sys.exit(1)

# Hidden imports for uvicorn and fastapi
hidden_imports = [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.http.httptools_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    'fastapi',
    'starlette',
    'pydantic',
    'cv2',
    'numpy',
    # Multiprocessing support for worker process
    'multiprocessing',
    'multiprocessing.connection',
    'multiprocessing.process',
    'multiprocessing.synchronize',
    'multiprocessing.queues',
    'multiprocessing.pool',
    # Worker module imports
    'worker',
    'ipc',
    'camera',
    'sessions',
    'processing',
    'ocr',
    'glyphs',
]

# Data files to include
datas = [
    # Include frontend build
    (str(frontend_dist), 'static'),
]

# Binary files (OpenCV may need some)
binaries = []

# Collect all Python source files to include them
collect_submodules = [
    'worker',
    'ipc', 
    'camera',
    'sessions',
    'processing',
    'ocr',
    'glyphs',
]

a = Analysis(
    ['main.py'],
    pathex=[str(backend_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary modules to reduce size
        'tkinter',
        'matplotlib',
        'scipy',
        # Heavy OCR deps we don't use (glyph engine only)
        'easyocr',
        'torch',
        'torchvision',
        'pytesseract',
        'PIL',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=output_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=is_release,  # UPX only for release builds (faster debug builds)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Set to False for no console window (but you lose CLI args visibility)
    disable_windowed_traceback=False,
    icon=None,  # Add path to .ico file for Windows icon
)
