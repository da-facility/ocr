# OCR Camera Application

Cross-platform application for camera capture with custom glyph-based OCR using template matching.

## Architecture

- **Backend**: Python FastAPI server (port 8000) with separate worker process for camera/OCR operations
- **Frontend**: Vue.js SPA with Tailwind CSS (dev port 5173)
- **OCR**: Custom glyph detection via template matching (no ML dependencies)
- **Image Pipeline**: Perspective correction → Color filtering → Morphology → OCR

## Directory Structure

```
ocr/
├── backend/           # Python FastAPI + worker
│   ├── main.py        # FastAPI server entry point
│   ├── worker.py      # Separate process for camera/OCR
│   ├── camera.py      # Camera management with ref-counted pooling
│   ├── sessions.py    # Data models and session persistence
│   ├── ocr.py         # OCR engine
│   ├── glyphs.py      # Glyph detection and template matching
│   └── processing.py  # Image processing pipeline
├── frontend/          # Vue.js SPA
│   └── src/
│       ├── views/     # HomeView, SessionView
│       └── components/
├── build.sh           # Build executable (Unix)
├── win-build.bat      # Build executable (Windows)
└── run.sh             # Start dev servers
```

## Technologies

- **Backend**: Python 3.9+, FastAPI, OpenCV, uv package manager
- **Frontend**: Vue 3, Vite, Tailwind CSS, Bun

## Development Commands

```bash
./run.sh              # Start dev servers (backend + frontend)
./build.sh            # Build executable (Unix)
win-build.bat         # Build executable (Windows)
```

## Architecture Notes

- Worker process isolation via IPC (multiprocessing.Pipe) for camera/OCR operations
- Reference-counted camera pooling for efficient resource management
- WebSocket endpoint for real-time OCR results streaming
- Session persistence in JSON files

## Coding Conventions

### Python (Backend)
- Type hints on all functions
- Dataclasses for data models
- Async/await for FastAPI endpoints
- snake_case naming

### Vue (Frontend)
- Composition API with `<script setup>`
- Tailwind CSS for styling
