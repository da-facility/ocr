---
name: Skip unstable time updates
overview: Make TimeValidator stateful to skip OCR updates containing "?" for time-type regions, returning the last stable reading instead.
todos:
  - id: update-time-validator
    content: Make TimeValidator stateful with last_stable_result tracking and is_stable flag
    status: completed
  - id: add-time-validator-storage
    content: Add time_validators dict and get_or_create_time_validator() method to WorkerState
    status: completed
  - id: use-persistent-validator
    content: Update handle_get_ocr_results() to use persistent time validators per region
    status: completed
isProject: false
---

# Skip Unstable Time OCR Updates

## Problem

When a time-type OCR region encounters uncertainty (represented by "?" in the detected text), the display updates with invalid/partial data. The user wants to skip these unstable readings and keep showing the last valid time.

## Solution

Make `TimeValidator` stateful (like `ScoreValidator` already is) to track the last stable result and return it when "?" is detected.

## Files to Modify

### 1. [backend/validators.py](backend/validators.py)

Add state tracking to `TimeValidator`:

```python
class TimeValidator:
    def __init__(self):
        self.last_stable_result: Optional[dict] = None
    
    def validate(self, text: str) -> dict:
        # Check for "?" indicating unstable reading
        if '?' in text:
            if self.last_stable_result:
                return {**self.last_stable_result, "is_stable": False}
            return {**self._empty_result(), "is_stable": False}
        
        # ... existing parsing logic ...
        result = self._parse_...()
        result["is_stable"] = True
        self.last_stable_result = result
        return result
```

### 2. [backend/worker.py](backend/worker.py)

Modify `WorkerState` class to store time validators per-region (similar to score validators):

- Add `self.time_validators: dict[str, dict[str, TimeValidator]]` storage
- Add `get_or_create_time_validator(session_id, region_id)` method

Update `handle_get_ocr_results()` to use persistent time validators instead of creating new ones each call:

```python
elif region_type == "time" and region_id:
    validator = state.get_or_create_time_validator(session_id, region_id)
    time_result = validator.validate(raw_text)
    validated_text = time_result["formatted"]
    extra_data["time"] = time_result
```

## Behavior

- When "?" is in the raw OCR text for a time region: return the last stable result with `is_stable: False`
- When no "?" is present: parse normally, store as last stable, return with `is_stable: True`
- If no previous stable result exists: return empty/zero result with `is_stable: False`

