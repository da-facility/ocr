---
name: Score Team Output Files
overview: Add team selection for score regions, create a combined score value ({home}:{away}), and implement file output functionality to save OCR results to a user-selected folder.
todos:
  - id: backend-models
    content: Add score_team to OcrRegion, output_folder to Session, and reserve "score" name validation in sessions.py
    status: pending
  - id: backend-main
    content: Add score_team to OcrRegionUpdate model and create output-folder endpoint in main.py
    status: pending
  - id: backend-worker
    content: Update worker.py to handle score_team, create combined score, and write output files
    status: pending
  - id: frontend-api
    content: Add updateOutputFolder function to api.js
    status: pending
  - id: frontend-ui
    content: Add team dropdown, fix formatting, reserve "score" name validation, and add Outputs section in OcrRegionSettings.vue
    status: pending
isProject: false
---

# Score Team Selection and File Output

## 1. Add Team Selection Dropdown

Add a new `score_team` field to track whether a score region represents "home", "away", or unspecified.

**Backend Changes ([sessions.py](backend/sessions.py)):**

- Add `score_team: Optional[str] = None` field to `OcrRegion` dataclass (line ~66)
- Update `to_dict()` and loading logic to include `score_team`

**Backend Changes ([main.py](backend/main.py)):**

- Add `score_team` to `OcrRegionUpdate` Pydantic model (line ~193)

**Backend Changes ([worker.py](backend/worker.py)):**

- Pass `score_team` through `handle_update_ocr_region` (line ~310)

**Frontend Changes ([OcrRegionSettings.vue](frontend/src/components/OcrRegionSettings.vue)):**

- Refactor score options to vertical layout (each selector on its own row with label)
- Add team selector dropdown with label "Team:" (around line 422)
- Add handler function `handleScoreTeamChange`
- Shorten "Singles (+/-1)" to just "Singles"
- Add "Mode:" label to the singles dropdown

## 2. Reserve "score" as Protected Name

The name "score" is reserved for the computed home:away value and cannot be used for OCR regions.

**Backend Changes ([sessions.py](backend/sessions.py)):**

- In `add_ocr_region()` and `update_ocr_region()`, reject if label is "score" (case-insensitive)
- Return `False` or raise an error

**Frontend Changes ([OcrRegionSettings.vue](frontend/src/components/OcrRegionSettings.vue)):**

- In `saveEdit()` function, check if name is "score" and reject with visual feedback
- Prevent submitting the rename if the name equals "score"

## 3. Create Combined Score Value

**Backend Changes ([worker.py](backend/worker.py)):**

- In `handle_get_ocr_results()` (line ~465), after processing all regions:
  - Find regions with `score_team == "home"` and `score_team == "away"`
  - Create a synthetic `score` result with format `{home_value}:{away_value}`
  - Add to the results dict

## 4. Add Outputs Section

**Backend Changes ([sessions.py](backend/sessions.py)):**

- Add `output_folder: Optional[str] = None` to `Session` dataclass (line ~100)

**Backend Changes ([main.py](backend/main.py)):**

- Add new endpoint `PUT /api/sessions/{session_id}/output-folder` to set the output path
- Add Pydantic model for the request

**Backend Changes ([worker.py](backend/worker.py)):**

- Add file writing logic in the OCR results loop
- Write each region's text to `{output_folder}/{region_name}.txt`
- Write combined score to `{output_folder}/score.txt`

**Frontend Changes ([api.js](frontend/src/api.js)):**

- Add `updateOutputFolder(sessionId, folderPath)` function

**Frontend Changes ([OcrRegionSettings.vue](frontend/src/components/OcrRegionSettings.vue)):**

- Add "Outputs" section after "API Endpoints" section (line ~729)
- Add folder path input with browse button (uses `<input type="file" webkitdirectory>` for folder selection)
- Display current output folder path
- Add clear button to disable output

## File Changes Summary

- `backend/sessions.py` - Add `score_team` to OcrRegion, `output_folder` to Session, reserve "score" name
- `backend/main.py` - Add `score_team` to update model, new output-folder endpoint
- `backend/worker.py` - Handle score_team, create combined score, write output files
- `frontend/src/api.js` - Add `updateOutputFolder` function
- `frontend/src/components/OcrRegionSettings.vue` - Team dropdown, fix formatting, "score" validation, Outputs section

## UI Layout for Score Type (Vertical Stack)

Each selector on its own line for better fit in the sidebar:

```
Type:    [Score    v]
Mode:    [Any      v]   <- Singles mode (Any/Singles)
Team:    [Any      v]   <- Team assignment (Any/Home/Away)
[Reset Validator]       <- Only shown when Mode=Singles
```

Dropdowns will use shorter labels:

- Mode: "Any" / "Singles" (instead of "Singles (+/-1)")
- Team: "Any" / "Home" / "Away"

