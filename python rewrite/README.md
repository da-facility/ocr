# OCR Console Python Rewrite

Tkinter/OpenCV rewrite of the OCR console. It keeps the core workflow close to the browser app:

- camera open/close with source picker
- static header, camera view, and output strip
- draw OCR zones on the viewer
- per-zone engine: `lexicon`, `digits`, or `tesseract`
- optional threshold + morphology processing
- real disk outputs only: folder, file, or URL webhook

## Run

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

On Windows:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
py app.py
```

`tesseract` output requires the Tesseract OCR binary to be installed on the machine. The `digits` engine does not.
