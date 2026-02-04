---
name: OCR Score Writer
overview: Create a Go program that connects to the OCR WebSocket, reads score and time data, and writes them to files in the current working directory.
todos:
  - id: go-mod
    content: Create `writer/go.mod` with gorilla/websocket dependency
    status: completed
  - id: main-go
    content: Create `writer/main.go` with WebSocket client, file writing, and reconnection logic
    status: completed
isProject: false
---

# OCR Score Writer Program

## Overview

A standalone Go binary that connects to the OCR WebSocket endpoint, extracts score and time values from OCR results, and writes them to `score.txt` and `time.txt` files in the current working directory.

## WebSocket Details

- **Endpoint**: `ws://{host}/ws/{session_id}/ocr`
- **Message format**: `{"results": {...}}` or `{"ping": true}`
- **Results structure** (keyed by region label):
  - Score regions: `score_value` (int), `text` (string)
  - Time regions: `time.formatted` (string like "12:34")

## Implementation

### File: `writer/main.go`

Single-file Go program with:

1. **Command-line flags**:
  - `--host` (default: `localhost:8000`) - Backend server address
  - `--session` (default: auto-detect first session)
  - `--home` (default: `Home`) - Home score region label
  - `--away` (default: `Away`) - Away score region label
  - `--time` (default: `Time`) - Time region label
2. **Session auto-detection**:
  - Fetch `GET /api/sessions` 
  - Use first session's ID if `--session` not provided
3. **Main loop**:
  ```
   while true:
     connect to WebSocket
     while connected:
       read message
       if results:
         extract home score from results[homeLabel].score_value
         extract away score from results[awayLabel].score_value  
         extract time from results[timeLabel].time.formatted
         write score.txt: "{home}:{away}"
         write time.txt: "{time}"
     sleep 500ms (reconnect delay)
  ```
4. **File writing**:
  - Atomic writes using temp file + rename pattern
  - Only write if value changed (avoid unnecessary disk I/O)

### Dependencies

Uses only Go standard library:

- `flag` - CLI args
- `net/http` - REST API calls
- `github.com/gorilla/websocket` - WebSocket client (single external dep)
- `encoding/json` - JSON parsing
- `os` - File operations

## File Structure

```
writer/
├── main.go      # Main program
└── go.mod       # Go module file
```

## Usage Examples

```bash
# Auto-detect first session, default region names
./writer

# Specify session ID
./writer --session abc123

# Custom region names
./writer --home "Home Score" --away "Away Score" --time "Clock"

# Different server
./writer --host 192.168.1.100:8000
```

