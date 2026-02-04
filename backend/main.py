from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os
import sys
import argparse
from pathlib import Path
import threading
from pydantic import BaseModel
from typing import Optional
import asyncio
import json
import mimetypes
import multiprocessing as mp
import time
import atexit

# Fix MIME types for Windows (Win10 registry often has .js as text/plain)
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("image/svg+xml", ".svg")

from ipc import IPCClient, Command, create_ipc_pair
from worker import start_worker_process
from processing import frame_to_jpeg

# Global worker process and IPC client
_worker_process: Optional[mp.Process] = None
_ipc_client: Optional[IPCClient] = None


def get_ipc_client() -> IPCClient:
    """Get the global IPC client, raising error if not initialized."""
    global _ipc_client
    if _ipc_client is None:
        raise RuntimeError("Worker not initialized")
    return _ipc_client


def ensure_worker_running():
    """Check if worker is running and restart if needed."""
    global _worker_process, _ipc_client
    
    if _worker_process is None or not _worker_process.is_alive():
        print("Starting/restarting worker process...")
        _worker_process, conn = start_worker_process()
        _ipc_client = IPCClient(conn, timeout=2.0)
        
        # Wait for worker to be ready
        for _ in range(50):  # 5 seconds max
            if _ipc_client.ping():
                print("Worker process ready")
                return
            time.sleep(0.1)
        
        print("Warning: Worker process not responding to ping")


def shutdown_worker():
    """Shutdown the worker process."""
    global _worker_process, _ipc_client
    
    if _ipc_client is not None:
        try:
            _ipc_client.send_command(Command.SHUTDOWN, timeout=2.0)
        except Exception:
            pass
        _ipc_client.close()
        _ipc_client = None
    
    if _worker_process is not None:
        _worker_process.join(timeout=3.0)
        if _worker_process.is_alive():
            _worker_process.terminate()
            _worker_process.join(timeout=1.0)
        _worker_process = None


# Determine paths based on whether running as exe or script
def get_base_path():
    """Get the base path for the application."""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe (PyInstaller)
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def get_static_path():
    """Get the path to static frontend files."""
    base = get_base_path()
    if getattr(sys, 'frozen', False):
        # In exe, static files are in 'static' folder
        return os.path.join(base, 'static')
    # In development, check for frontend dist
    return os.path.join(os.path.dirname(base), 'frontend', 'dist')


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown events."""
    # Startup
    print("Starting OCR Camera Backend...")
    ensure_worker_running()

    # Register cleanup
    atexit.register(shutdown_worker)

    try:
        yield  # App is running
    except asyncio.CancelledError:
        # Normal during Ctrl+C shutdown
        pass
    finally:
        # Shutdown
        print("Shutting down OCR Camera Backend...")
        shutdown_worker()


app = FastAPI(title="OCR Camera Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with timing."""
    start = time.time()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    # Skip logging for stream endpoints (too noisy)
    if not request.url.path.startswith("/stream/"):
        print(f"[{request.method}] {request.url.path} -> {response.status_code} ({duration:.0f}ms)")
    return response


class CreateSessionRequest(BaseModel):
    camera_index: int
    camera_name: str = ""
    camera_device_name: str = ""
    camera_vid: Optional[int] = None
    camera_pid: Optional[int] = None


class PerspectiveRequest(BaseModel):
    points: Optional[list[list[int]]]
    output_size: Optional[list[int]] = None


class ColorFilterRequest(BaseModel):
    bgr: list[int]
    tolerance: list[int] = [30, 30, 30]


class ColorFilterUpdateRequest(BaseModel):
    tolerance: list[int]


class MorphologyRequest(BaseModel):
    erosion_kernel: Optional[int] = None
    dilation_kernel: Optional[int] = None


class PickColorRequest(BaseModel):
    x: int
    y: int


class OcrRegionRequest(BaseModel):
    x: int
    y: int
    width: int
    height: int
    label: str = ""


class OcrRegionUpdateRequest(BaseModel):
    x: Optional[int] = None
    y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    label: Optional[str] = None
    ocr_backend: Optional[str] = None
    region_type: Optional[str] = None  # "generic", "time", "score"
    score_subtype: Optional[str] = None  # For score type: None or "singles"
    score_team: Optional[str] = None  # For score type: None, "home", or "away"


class OutputFolderRequest(BaseModel):
    folder_path: Optional[str] = None


@app.get("/api/cameras")
async def list_cameras(refresh: bool = False):
    """List available camera devices. Uses cache for instant response unless refresh=true."""
    client = get_ipc_client()
    response = client.send_command(Command.LIST_CAMERAS, force_refresh=refresh, timeout=5.0)
    if not response.success:
        raise HTTPException(status_code=500, detail=response.error or "Failed to list cameras")
    print(f"[API] /api/cameras returning {len(response.data) if response.data else 0} cameras")
    return {"cameras": response.data}


@app.post("/api/cameras/refresh")
async def refresh_cameras():
    """Force refresh the camera list and return updated data."""
    client = get_ipc_client()
    response = client.send_command(Command.REFRESH_CAMERAS, timeout=5.0)
    if not response.success:
        raise HTTPException(status_code=500, detail=response.error or "Failed to refresh cameras")
    return {"cameras": response.data}


@app.get("/api/sessions")
async def list_sessions():
    """List all active sessions."""
    client = get_ipc_client()
    response = client.send_command(Command.LIST_SESSIONS)
    if not response.success:
        raise HTTPException(status_code=500, detail=response.error or "Failed to list sessions")
    print(f"[API] /api/sessions returning {len(response.data) if response.data else 0} sessions")
    return {"sessions": response.data}


@app.post("/api/sessions")
async def create_session(request: CreateSessionRequest):
    """Create a new capture session."""
    client = get_ipc_client()
    response = client.send_command(
        Command.CREATE_SESSION,
        camera_index=request.camera_index,
        camera_name=request.camera_name,
        camera_device_name=request.camera_device_name,
        camera_vid=request.camera_vid,
        camera_pid=request.camera_pid,
        timeout=5.0
    )
    
    if not response.success or response.data is None:
        raise HTTPException(status_code=400, detail=response.error or "Failed to open camera")
    
    # Subscribe file writer if configured
    file_writer = get_file_writer()
    if file_writer:
        file_writer.subscribe_to_session(response.data['id'])
    
    return response.data


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session details."""
    client = get_ipc_client()
    response = client.send_command(Command.GET_SESSION, session_id=session_id)
    if not response.success or response.data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return response.data


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and release the camera."""
    client = get_ipc_client()
    response = client.send_command(Command.DELETE_SESSION, session_id=session_id)
    if not response.success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}


@app.put("/api/sessions/{session_id}/perspective")
async def update_perspective(session_id: str, request: PerspectiveRequest):
    """Update perspective correction points and output size."""
    client = get_ipc_client()
    response = client.send_command(
        Command.UPDATE_PERSPECTIVE,
        session_id=session_id,
        points=request.points,
        output_size=request.output_size
    )
    if not response.success or response.data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return response.data


@app.post("/api/sessions/{session_id}/color-filters")
async def add_color_filter(session_id: str, request: ColorFilterRequest):
    """Add a new color filter."""
    client = get_ipc_client()
    response = client.send_command(
        Command.ADD_COLOR_FILTER,
        session_id=session_id,
        bgr=request.bgr,
        tolerance=request.tolerance
    )
    if not response.success or response.data is None:
        raise HTTPException(status_code=400, detail="Failed to add color filter")
    return response.data


@app.put("/api/sessions/{session_id}/color-filters/{filter_id}")
async def update_color_filter(session_id: str, filter_id: str, request: ColorFilterUpdateRequest):
    """Update a color filter's tolerance."""
    client = get_ipc_client()
    response = client.send_command(
        Command.UPDATE_COLOR_FILTER,
        session_id=session_id,
        filter_id=filter_id,
        tolerance=request.tolerance
    )
    if not response.success or not response.data:
        raise HTTPException(status_code=404, detail="Session or filter not found")
    return {"status": "updated"}


@app.delete("/api/sessions/{session_id}/color-filters/{filter_id}")
async def delete_color_filter(session_id: str, filter_id: str):
    """Delete a color filter."""
    client = get_ipc_client()
    response = client.send_command(
        Command.DELETE_COLOR_FILTER,
        session_id=session_id,
        filter_id=filter_id
    )
    if not response.success or not response.data:
        raise HTTPException(status_code=404, detail="Session or filter not found")
    return {"status": "deleted"}


@app.delete("/api/sessions/{session_id}/color-filters")
async def clear_color_filters(session_id: str):
    """Clear all color filters."""
    client = get_ipc_client()
    response = client.send_command(Command.CLEAR_COLOR_FILTERS, session_id=session_id)
    if not response.success or not response.data:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "cleared"}


@app.put("/api/sessions/{session_id}/morphology")
async def update_morphology(session_id: str, request: MorphologyRequest):
    """Update morphology settings."""
    client = get_ipc_client()
    response = client.send_command(
        Command.UPDATE_MORPHOLOGY,
        session_id=session_id,
        erosion_kernel=request.erosion_kernel,
        dilation_kernel=request.dilation_kernel
    )
    if not response.success or response.data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return response.data


@app.put("/api/sessions/{session_id}/output-folder")
async def update_output_folder(session_id: str, request: OutputFolderRequest):
    """Update the output folder for OCR results."""
    client = get_ipc_client()
    response = client.send_command(
        Command.UPDATE_OUTPUT_FOLDER,
        session_id=session_id,
        output_folder=request.folder_path
    )
    if not response.success or not response.data:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "updated", "output_folder": request.folder_path}


@app.post("/api/sessions/{session_id}/pick-color")
async def pick_color(session_id: str, request: PickColorRequest):
    """Pick a color from the perspective-corrected frame at given coordinates."""
    client = get_ipc_client()
    response = client.send_command(
        Command.PICK_COLOR,
        session_id=session_id,
        x=request.x,
        y=request.y
    )
    if not response.success or response.data is None:
        raise HTTPException(status_code=400, detail="Failed to pick color")
    return response.data


@app.post("/api/sessions/{session_id}/ocr-regions")
async def add_ocr_region(session_id: str, request: OcrRegionRequest):
    """Add an OCR region."""
    client = get_ipc_client()
    response = client.send_command(
        Command.ADD_OCR_REGION,
        session_id=session_id,
        x=request.x,
        y=request.y,
        width=request.width,
        height=request.height,
        label=request.label
    )
    if not response.success or response.data is None:
        raise HTTPException(status_code=400, detail="Failed to add OCR region")
    return response.data


@app.put("/api/sessions/{session_id}/ocr-regions/{region_id}")
async def update_ocr_region(session_id: str, region_id: str, request: OcrRegionUpdateRequest):
    """Update an OCR region."""
    client = get_ipc_client()
    response = client.send_command(
        Command.UPDATE_OCR_REGION,
        session_id=session_id,
        region_id=region_id,
        x=request.x,
        y=request.y,
        width=request.width,
        height=request.height,
        label=request.label,
        ocr_backend=request.ocr_backend,
        region_type=request.region_type,
        score_subtype=request.score_subtype,
        score_team=request.score_team
    )
    if not response.success or not response.data:
        raise HTTPException(status_code=400, detail="Session/region not found or name already exists")
    return {"status": "updated"}


@app.post("/api/sessions/{session_id}/ocr-regions/{region_id}/reset-validator")
async def reset_region_validator(session_id: str, region_id: str):
    """Reset the validator for a score region (allows any next value)."""
    client = get_ipc_client()
    response = client.send_command(
        Command.RESET_REGION_VALIDATOR,
        session_id=session_id,
        region_id=region_id
    )
    if not response.success or not response.data:
        raise HTTPException(status_code=404, detail="Session or region not found")
    return {"status": "reset"}


@app.delete("/api/sessions/{session_id}/ocr-regions/{region_id}")
async def delete_ocr_region(session_id: str, region_id: str):
    """Delete an OCR region."""
    client = get_ipc_client()
    response = client.send_command(
        Command.DELETE_OCR_REGION,
        session_id=session_id,
        region_id=region_id
    )
    if not response.success or not response.data:
        raise HTTPException(status_code=404, detail="Session or region not found")
    return {"status": "deleted"}


@app.delete("/api/sessions/{session_id}/ocr-regions")
async def clear_ocr_regions(session_id: str):
    """Clear all OCR regions."""
    client = get_ipc_client()
    response = client.send_command(Command.CLEAR_OCR_REGIONS, session_id=session_id)
    if not response.success or not response.data:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "cleared"}


# ============= Glyph Management =============

class GlyphRequest(BaseModel):
    char: str
    template: list[list[int]]
    width: int
    height: int
    ignored: bool = False


class GlyphUpdateRequest(BaseModel):
    char: Optional[str] = None
    ignored: Optional[bool] = None


@app.get("/api/sessions/{session_id}/glyphs")
async def list_glyphs(session_id: str):
    """List all glyphs for a session."""
    client = get_ipc_client()
    response = client.send_command(Command.LIST_GLYPHS, session_id=session_id)
    if not response.success or response.data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"glyphs": response.data}


@app.post("/api/sessions/{session_id}/glyphs")
async def add_glyph(session_id: str, request: GlyphRequest):
    """Add a new glyph template."""
    client = get_ipc_client()
    response = client.send_command(
        Command.ADD_GLYPH,
        session_id=session_id,
        char=request.char,
        template=request.template,
        width=request.width,
        height=request.height,
        ignored=request.ignored
    )
    if not response.success or response.data is None:
        raise HTTPException(status_code=400, detail="Failed to add glyph")
    return response.data


@app.put("/api/sessions/{session_id}/glyphs/{glyph_id}")
async def update_glyph(session_id: str, glyph_id: str, request: GlyphUpdateRequest):
    """Update a glyph's character label or ignored status."""
    client = get_ipc_client()
    response = client.send_command(
        Command.UPDATE_GLYPH,
        session_id=session_id,
        glyph_id=glyph_id,
        char=request.char,
        ignored=request.ignored
    )
    if not response.success or not response.data:
        raise HTTPException(status_code=404, detail="Session or glyph not found")
    return {"status": "updated"}


@app.delete("/api/sessions/{session_id}/glyphs/{glyph_id}")
async def delete_glyph(session_id: str, glyph_id: str):
    """Delete a glyph."""
    client = get_ipc_client()
    response = client.send_command(
        Command.DELETE_GLYPH,
        session_id=session_id,
        glyph_id=glyph_id
    )
    if not response.success or not response.data:
        raise HTTPException(status_code=404, detail="Session or glyph not found")
    return {"status": "deleted"}


@app.delete("/api/sessions/{session_id}/glyphs")
async def clear_glyphs(session_id: str):
    """Clear all glyphs."""
    client = get_ipc_client()
    response = client.send_command(Command.CLEAR_GLYPHS, session_id=session_id)
    if not response.success or not response.data:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "cleared"}


@app.get("/api/sessions/{session_id}/detect-glyphs")
async def detect_glyphs(session_id: str, region_id: Optional[str] = None, 
                        merge_vertical: bool = False):
    """
    Detect glyphs in the current processed frame for training.
    Returns detected glyphs with their templates for labeling.
    """
    client = get_ipc_client()
    response = client.send_command(
        Command.DETECT_GLYPHS,
        session_id=session_id,
        region_id=region_id,
        merge_vertical=merge_vertical,
        timeout=5.0
    )
    if not response.success or response.data is None:
        raise HTTPException(status_code=400, detail="Failed to detect glyphs")
    return response.data


class CombineGlyphsRequest(BaseModel):
    indices: list[int]
    region_id: Optional[str] = None


@app.post("/api/sessions/{session_id}/combine-glyphs")
async def combine_glyphs(session_id: str, request: CombineGlyphsRequest):
    """
    Combine multiple detected glyphs into a single template.
    Used for characters like ':' that are detected as separate components.
    """
    client = get_ipc_client()
    response = client.send_command(
        Command.COMBINE_GLYPHS,
        session_id=session_id,
        indices=request.indices,
        region_id=request.region_id,
        timeout=5.0
    )
    if not response.success or response.data is None:
        raise HTTPException(status_code=400, detail="Invalid glyph indices")
    return response.data


# ============= Global Glyph Storage =============

@app.get("/api/glyph-sets")
async def list_glyph_sets():
    """List all global glyph sets."""
    client = get_ipc_client()
    response = client.send_command(Command.LIST_GLYPH_SETS)
    if not response.success:
        raise HTTPException(status_code=500, detail=response.error or "Failed to list glyph sets")
    return {"glyph_sets": response.data}


@app.get("/api/glyph-sets/{set_id}")
async def get_glyph_set(set_id: str):
    """Get a specific glyph set with all its glyphs."""
    client = get_ipc_client()
    response = client.send_command(Command.GET_GLYPH_SET, set_id=set_id)
    if not response.success or response.data is None:
        raise HTTPException(status_code=404, detail="Glyph set not found")
    return response.data


class CreateGlyphSetRequest(BaseModel):
    name: str
    glyphs: list[dict]


@app.post("/api/glyph-sets")
async def create_glyph_set(request: CreateGlyphSetRequest):
    """Create a new glyph set from provided glyphs."""
    client = get_ipc_client()
    response = client.send_command(
        Command.CREATE_GLYPH_SET,
        name=request.name,
        glyphs=request.glyphs
    )
    if not response.success or response.data is None:
        raise HTTPException(status_code=400, detail="Failed to create glyph set")
    return response.data


@app.delete("/api/glyph-sets/{set_id}")
async def delete_glyph_set(set_id: str):
    """Delete a glyph set."""
    client = get_ipc_client()
    response = client.send_command(Command.DELETE_GLYPH_SET, set_id=set_id)
    if not response.success or not response.data:
        raise HTTPException(status_code=404, detail="Glyph set not found")
    return {"status": "deleted"}


class ExportGlyphsRequest(BaseModel):
    name: str


@app.post("/api/sessions/{session_id}/export-glyphs")
async def export_glyphs(session_id: str, request: ExportGlyphsRequest):
    """Export all glyphs from a session to a new global glyph set."""
    client = get_ipc_client()
    response = client.send_command(
        Command.EXPORT_GLYPHS,
        session_id=session_id,
        name=request.name
    )
    if not response.success or response.data is None:
        raise HTTPException(status_code=400, detail="Failed to export glyphs (no glyphs in session?)")
    return response.data


class ImportGlyphsRequest(BaseModel):
    set_id: str
    replace: bool = False


@app.post("/api/sessions/{session_id}/import-glyphs")
async def import_glyphs(session_id: str, request: ImportGlyphsRequest):
    """Import a glyph set into a session."""
    client = get_ipc_client()
    response = client.send_command(
        Command.IMPORT_GLYPHS,
        session_id=session_id,
        set_id=request.set_id,
        replace=request.replace
    )
    if not response.success or not response.data:
        raise HTTPException(status_code=400, detail="Failed to import glyphs")
    return {"status": "imported"}


def generate_mjpeg_stream(session_id: str, stream_type: str):
    """Generator for MJPEG streaming with timeout handling."""
    client = get_ipc_client()
    last_frame = None
    
    while True:
        frame, is_stale = client.get_frame(session_id, stream_type)
        
        if frame is not None:
            last_frame = frame
            jpeg = frame_to_jpeg(frame)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            )
        elif last_frame is not None:
            # Return cached frame on timeout
            jpeg = frame_to_jpeg(last_frame)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            )
        else:
            # No frame available, yield empty and sleep briefly
            time.sleep(0.1)
        
        # Small delay to limit frame rate
        time.sleep(0.033)  # ~30 fps max


@app.get("/stream/{session_id}/original")
async def stream_original(session_id: str):
    """MJPEG stream of original camera feed."""
    client = get_ipc_client()
    response = client.send_command(Command.GET_SESSION, session_id=session_id)
    if not response.success or response.data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return StreamingResponse(
        generate_mjpeg_stream(session_id, "original"),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/stream/{session_id}/perspective")
async def stream_perspective(session_id: str):
    """MJPEG stream with perspective correction applied."""
    client = get_ipc_client()
    response = client.send_command(Command.GET_SESSION, session_id=session_id)
    if not response.success or response.data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return StreamingResponse(
        generate_mjpeg_stream(session_id, "perspective"),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/stream/{session_id}/processed")
async def stream_processed(session_id: str):
    """MJPEG stream with full processing (perspective + color/morphology)."""
    client = get_ipc_client()
    response = client.send_command(Command.GET_SESSION, session_id=session_id)
    if not response.success or response.data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return StreamingResponse(
        generate_mjpeg_stream(session_id, "processed"),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.websocket("/ws/{session_id}/ocr")
async def websocket_ocr(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time OCR results."""
    client = get_ipc_client()
    response = client.send_command(Command.GET_SESSION, session_id=session_id)
    if not response.success or response.data is None:
        await websocket.close(code=4004)
        return
    
    await websocket.accept()
    
    try:
        while True:
            # Poll for OCR results with caching
            results, is_stale = client.get_ocr_results(session_id)
            
            if results is not None:
                await websocket.send_text(json.dumps({"results": results}))
            else:
                await websocket.send_text(json.dumps({"ping": True}))
            
            await asyncio.sleep(0.5)  # Poll every 500ms
            
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@app.get("/ocr/{session_id}")
async def get_ocr_results(session_id: str):
    """Get all OCR results for a session as JSON."""
    client = get_ipc_client()
    response = client.send_command(Command.GET_SESSION, session_id=session_id)
    if not response.success or response.data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    results_response = client.send_command(Command.GET_OCR_RESULTS, session_id=session_id)
    if not results_response.success or results_response.data is None:
        return {}
    
    return results_response.data


@app.get("/ocr/{session_id}/{region_name}", response_class=PlainTextResponse)
async def get_ocr_region_text(session_id: str, region_name: str):
    """Get plain text OCR result for a specific region."""
    client = get_ipc_client()
    response = client.send_command(Command.GET_SESSION, session_id=session_id)
    if not response.success or response.data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    text_response = client.send_command(
        Command.GET_REGION_TEXT,
        session_id=session_id,
        region_name=region_name
    )
    
    if not text_response.success or text_response.data is None:
        raise HTTPException(status_code=404, detail="Region not found or no results")
    
    return text_response.data


DEBUG_DIR = "./debug"


@app.get("/debug/{session_id}")
async def list_debug_images(session_id: str):
    """List all debug images for a session."""
    client = get_ipc_client()
    response = client.send_command(Command.GET_SESSION, session_id=session_id)
    if not response.success or response.data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session_dir = os.path.join(DEBUG_DIR, session_id)
    if not os.path.exists(session_dir):
        return {"images": []}
    
    images = []
    for filename in os.listdir(session_dir):
        if filename.endswith('.png'):
            images.append({
                "region": filename.replace('.png', ''),
                "url": f"/debug/{session_id}/{filename}"
            })
    
    return {"images": images}


@app.get("/debug/{session_id}/{filename}")
async def get_debug_image(session_id: str, filename: str):
    """Get a specific debug image."""
    filepath = os.path.join(DEBUG_DIR, session_id, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Debug image not found")
    
    return FileResponse(filepath, media_type="image/png")


# ============= Static File Serving (for production/exe) =============

def setup_static_files():
    """Mount static files if frontend build exists."""
    static_path = get_static_path()
    if os.path.exists(static_path) and os.path.isdir(static_path):
        # Serve static assets
        app.mount("/assets", StaticFiles(directory=os.path.join(static_path, "assets")), name="assets")
        
        # Serve index.html for all non-API routes (SPA fallback)
        index_path = os.path.join(static_path, "index.html")
        if os.path.exists(index_path):
            @app.get("/", response_class=HTMLResponse)
            async def serve_index():
                with open(index_path, 'r') as f:
                    return f.read()
            
            # Catch-all for SPA routing (must be last)
            @app.get("/{path:path}", response_class=HTMLResponse)
            async def serve_spa(path: str):
                # Don't catch API routes, streams, websockets, etc.
                if path.startswith(('api/', 'stream/', 'ws/', 'ocr/', 'debug/')):
                    raise HTTPException(status_code=404)
                with open(index_path, 'r') as f:
                    return f.read()
        
        print(f"Static files mounted from: {static_path}")
        return True
    return False


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="OCR Camera Backend Server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address to bind to"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open browser on startup"
    )
    parser.add_argument(
        "--directory", "-d",
        type=str,
        default=None,
        help="Directory to save OCR results. Creates path/[session_id]/[region_name].txt files"
    )
    parser.add_argument(
        "--clean-logs",
        action="store_true",
        help="Disable ANSI color codes in logs (useful for Windows CMD/PowerShell)"
    )
    return parser.parse_args()


def should_use_clean_logs() -> bool:
    """
    Auto-detect if we should disable ANSI color codes.
    Returns True for Windows terminals that don't support ANSI.
    """
    if sys.platform != "win32":
        return False
    
    # Check if running in Windows Terminal or other modern terminal
    # that supports ANSI codes via WT_SESSION or TERM_PROGRAM
    if os.environ.get("WT_SESSION"):
        return False  # Windows Terminal supports ANSI
    if os.environ.get("TERM_PROGRAM"):
        return False  # Modern terminal (e.g., VSCode integrated terminal)
    
    # Check if virtual terminal processing is enabled
    # This is typically NOT enabled in legacy CMD/PowerShell
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # STD_OUTPUT_HANDLE = -11
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            if mode.value & 0x0004:
                return False  # VT processing enabled
    except Exception:
        pass
    
    # Default: assume legacy Windows terminal without ANSI support
    return True


def configure_logging(clean_logs: bool):
    """Configure logging to optionally disable ANSI color codes."""
    import logging
    
    if clean_logs:
        # Use a simple formatter without colors
        log_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(levelname)s:     %(message)s",
                },
                "access": {
                    "format": '%(levelname)s:     %(client_addr)s - "%(request_line)s" %(status_code)s',
                },
            },
            "handlers": {
                "default": {
                    "formatter": "default",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stderr",
                },
                "access": {
                    "formatter": "access",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                },
            },
            "loggers": {
                "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
                "uvicorn.error": {"level": "INFO"},
                "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
            },
        }
        return log_config
    return None


def open_browser(host: str, port: int):
    """Open the default browser to the app URL."""
    import webbrowser
    import time
    
    def _open():
        time.sleep(1.5)  # Wait for server to start
        url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}"
        webbrowser.open(url)
        print(f"Opened browser at {url}")
    
    threading.Thread(target=_open, daemon=True).start()


class OCRFileWriter:
    """Writes OCR results to files in a specified directory."""
    
    def __init__(self, base_directory: str):
        self.base_path = Path(base_directory).resolve()
        self._subscribed_sessions: set[str] = set()
        self._lock = threading.Lock()
        self._running = True
        self._poll_thread: Optional[threading.Thread] = None
        
        # Create base directory if it doesn't exist
        self.base_path.mkdir(parents=True, exist_ok=True)
        print(f"OCR results will be saved to: {self.base_path}")
    
    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string to be safe for use as a filename on all platforms."""
        # Replace characters that are invalid on Windows/Linux/macOS
        invalid_chars = '<>:"/\\|?*'
        result = name
        for char in invalid_chars:
            result = result.replace(char, '_')
        # Also handle leading/trailing spaces and dots (Windows issues)
        result = result.strip('. ')
        return result or 'unnamed'
    
    def _write_results(self, session_id: str, results: dict):
        """Write OCR results to files."""
        # Create session directory
        session_dir = self.base_path / self._sanitize_filename(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        
        for region_name, region_data in results.items():
            if region_name == '_full':
                continue  # Skip full-frame results
            
            # Get text from region data
            text = region_data.get('text', '').strip() if isinstance(region_data, dict) else ''
            
            # Write to file
            filename = self._sanitize_filename(region_name) + '.txt'
            filepath = session_dir / filename
            
            try:
                filepath.write_text(text, encoding='utf-8')
            except Exception as e:
                print(f"Error writing OCR result to {filepath}: {e}")
    
    def _poll_loop(self):
        """Poll for OCR results and write them."""
        while self._running:
            with self._lock:
                sessions = list(self._subscribed_sessions)
            
            client = None
            try:
                client = get_ipc_client()
            except RuntimeError:
                pass
            
            if client:
                for session_id in sessions:
                    results, _ = client.get_ocr_results(session_id)
                    if results:
                        self._write_results(session_id, results)
            
            time.sleep(0.5)
    
    def subscribe_to_session(self, session_id: str):
        """Subscribe to OCR results for a session."""
        with self._lock:
            self._subscribed_sessions.add(session_id)
        
        # Start poll thread if not running
        if self._poll_thread is None or not self._poll_thread.is_alive():
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread.start()
        
        print(f"Subscribed to OCR results for session {session_id}")
    
    def subscribe_all_sessions(self):
        """Subscribe to all existing sessions."""
        try:
            client = get_ipc_client()
            response = client.send_command(Command.LIST_SESSIONS)
            if response.success and response.data:
                for session in response.data:
                    self.subscribe_to_session(session['id'])
        except RuntimeError:
            pass
    
    def stop(self):
        """Stop the file writer."""
        self._running = False


# Global file writer instance (set from main)
_ocr_file_writer: OCRFileWriter | None = None


def setup_file_writer(directory: str):
    """Setup the OCR file writer."""
    global _ocr_file_writer
    _ocr_file_writer = OCRFileWriter(directory)
    _ocr_file_writer.subscribe_all_sessions()
    return _ocr_file_writer


def get_file_writer() -> OCRFileWriter | None:
    """Get the global file writer instance."""
    return _ocr_file_writer


if __name__ == "__main__":
    # Required for Windows multiprocessing
    mp.freeze_support()
    
    import uvicorn
    
    args = parse_args()
    
    # Determine if we should use clean (no ANSI) logs
    use_clean_logs = args.clean_logs or should_use_clean_logs()
    log_config = configure_logging(use_clean_logs)
    
    # Setup static files for production
    has_static = setup_static_files()
    
    print(f"Starting OCR Camera Backend...")
    print(f"Host: {args.host}")
    print(f"Port: {args.port}")
    print(f"Static files: {'Yes' if has_static else 'No (run frontend dev server separately)'}")
    if use_clean_logs:
        print("Clean logs: Enabled (ANSI color codes disabled)")
    
    # Setup file writer if directory specified
    if args.directory:
        setup_file_writer(args.directory)
    
    # Open browser if static files available and not disabled
    if has_static and not args.no_browser:
        open_browser(args.host, args.port)

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_config=log_config)
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl+C
