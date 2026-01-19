# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for OCR Camera App.

Build with:
    pyinstaller ocr-camera.spec

Prerequisites:
    1. Build frontend first: cd ../frontend && npm run build
    2. Install PyInstaller: pip install pyinstaller
    3. Make sure all dependencies are installed
"""

import sys
from pathlib import Path

# Paths
backend_dir = Path(SPECPATH)
frontend_dist = backend_dir.parent / 'frontend' / 'dist'

# Check if frontend is built
if not frontend_dist.exists():
    print("ERROR: Frontend not built! Run 'npm run build' in frontend/ first.")
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
    'PIL',
    'pytesseract',
    # EasyOCR imports (large, can be removed if not using)
    'easyocr',
    'torch',
    'torchvision',
]

# Data files to include
datas = [
    # Include frontend build
    (str(frontend_dist), 'static'),
]

# Binary files (OpenCV may need some)
binaries = []

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
    name='OCR-Camera',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Set to False for no console window (but you lose CLI args visibility)
    disable_windowed_traceback=False,
    icon=None,  # Add path to .ico file for Windows icon
)
