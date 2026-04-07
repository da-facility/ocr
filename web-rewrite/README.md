# Browser OCR Rewrite

Minimal Solid.js rewrite of the OCR camera tool that runs entirely in the browser.

## What it does

- Captures a camera with `getUserMedia`
- Lets you place and drag 4 perspective points
- Builds a thresholded black/white processing view
- Lets you draw and rename OCR zones
- Detects glyph candidates from a selected zone
- Saves a browser-side glyph lexicon in `localStorage`
- Runs simple glyph-template OCR in the page
- Writes live OCR output to a chosen folder or file when the browser supports the File System Access API

## Run

```bash
bun install
bun run dev
```

Then open the Vite URL, allow camera access, and work from the single screen UI.

## Browser notes

- Camera capture needs a secure context in normal browser deployments.
- Live file writing works best in Chromium-based browsers because it depends on `showDirectoryPicker` / `showSaveFilePicker`.
- If that API is missing, the OCR app still runs, but direct filesystem output is unavailable.

## Build

```bash
bun run build
```
