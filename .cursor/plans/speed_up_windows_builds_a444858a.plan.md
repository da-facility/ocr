---
name: Speed up Windows builds
overview: Make packaged Windows builds incremental and stop bundling heavyweight OCR deps you don’t use; default packaging build is debug-friendly (frontend sourcemaps, no UPX) and `--release` is the slimmest exe.
todos:
  - id: remove-unused-ocr-deps
    content: Remove `easyocr` and `pytesseract` from backend deps and update `uv.lock`.
    status: completed
  - id: stop-forcing-ml-imports
    content: Edit `backend/ocr-camera.spec` to remove heavy `hidden_imports` and add `excludes` guardrails.
    status: completed
  - id: add-debug-frontend-build
    content: Add a `frontend` build script that emits sourcemaps for the packaged debug build.
    status: completed
  - id: make-build-script-incremental
    content: Update `win-build.bat` to avoid `--clean` by default and support `--release` (default is debug-friendly onefile exe; release is smallest).
    status: completed
isProject: false
---

# Speed up Windows builds

## What’s slow today (root causes)

- Your `win-build.bat` runs PyInstaller with `--clean`, which deletes PyInstaller’s build/cache artifacts; that’s why you always see `PKG-00.toc is non existent` and it rebuilds the huge appended archive every time.
- Your `backend/ocr-camera.spec` explicitly forces `pytesseract`, `easyocr`, `torch`, `torchvision` via `hidden_imports`, so PyInstaller drags in all their hooks/transitive deps (your log shows it clearly) even though the backend code uses the glyph engine.
- You rebuild the frontend every time; because the spec bundles `frontend/dist` as `datas`, that also tends to force a repack.

## Changes (high impact)

- Update `[backend/pyproject.toml](c:/Users/katal-r/source/ocr/backend/pyproject.toml)` to remove `easyocr` and `pytesseract` from `dependencies` (you confirmed you don’t use them). Regenerate `backend/uv.lock` after.
- Update `[backend/ocr-camera.spec](c:/Users/katal-r/source/ocr/backend/ocr-camera.spec)`:
  - Remove `easyocr/torch/torchvision/pytesseract` from `hidden_imports`.
  - Add them to `excludes` as a safety net so they can’t get bundled even if installed.
- Add a debug frontend build script in `[frontend/package.json](c:/Users/katal-r/source/ocr/frontend/package.json)` that generates JS sourcemaps for packaged debugging (e.g. `vite build --sourcemap`).
- Update `[win-build.bat](c:/Users/katal-r/source/ocr/win-build.bat)` to be a **packaging builder** with two modes (both still build a single exe):
  - **Default (debug-friendly onefile)**:
    - Keep PyInstaller incremental: remove `--clean` by default.
    - Disable UPX (`--noupx`) to avoid slow compression during iteration.
    - Build frontend with sourcemaps (`bun run build:debug`).
  - **--release (slimmest onefile)**:
    - Frontend build without sourcemaps (`bun run build`).
    - Enable UPX (keep `upx=True` in spec and don’t pass `--noupx`).
    - Keep the same `excludes` guardrails so heavy OCR deps never get pulled in.

The big win you’ll feel immediately: once `--clean` is gone, the second and later packaging builds should not rebuild `PKG-00.toc` unless inputs changed (the first build after changes will still be a full build).

## Commands you’ll run after the code changes

- Backend lock/sync (after removing deps):
  - `cd backend; uv lock; uv sync --frozen`
- Packaged debug-friendly build (single exe):
  - `win-build.bat`
- Packaged release build (slimmest single exe):
  - `win-build.bat --release`

## Notes

- `uv sync` installs the `dev` dependency-group by default; we can move `pyinstaller` from `[project.optional-dependencies]` into `[dependency-groups].dev` so you can drop the extra `uv pip install pyinstaller` step and keep builds reproducible.

