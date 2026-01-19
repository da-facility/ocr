from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os
import sys
import argparse
from pydantic import BaseModel
from typing import Optional
import asyncio
import json

from sessions import session_manager
from camera import camera_manager
from processing import process_frame_perspective, process_frame_full, frame_to_jpeg, get_color_at_point
from ocr import ocr_manager
from glyphs import get_detected_glyphs_for_training, combine_glyphs_by_indices, GLYPH_SIZE

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

app = FastAPI(title="OCR Camera Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def start_session_ocr(session):
    """Helper to start OCR for a session."""
    def get_processed_frame():
        sess = session_manager.get_session(session.id)
        if sess is None:
            return None
        cam = camera_manager.get_camera(sess.camera_index)
        if cam is None:
            return None
        frame = cam.get_frame()
        if frame is None:
            return None
        return process_frame_full(
            frame,
            perspective_points=sess.perspective_points,
            output_size=sess.perspective_output_size,
            color_filters=[cf.to_dict() for cf in sess.color_filters],
            erosion_kernel=sess.erosion_kernel,
            dilation_kernel=sess.dilation_kernel
        )
    
    def get_regions():
        sess = session_manager.get_session(session.id)
        if sess is None:
            return []
        return [r.to_dict() for r in sess.ocr_regions]
    
    def get_glyphs():
        sess = session_manager.get_session(session.id)
        if sess is None:
            return []
        return [g.to_dict() for g in sess.glyphs]
    
    ocr_manager.start_ocr(session.id, get_processed_frame, get_regions, get_glyphs)


@app.on_event("startup")
async def startup_event():
    """Initialize cameras and OCR for loaded sessions."""
    for session in session_manager.list_sessions():
        camera = camera_manager.acquire_camera(session.camera_index)
        if camera:
            start_session_ocr(session)
            print(f"Restored session {session.id} with camera {session.camera_index}")
        else:
            print(f"Failed to restore session {session.id}: camera {session.camera_index} not available")


class CreateSessionRequest(BaseModel):
    camera_index: int
    camera_name: str = ""


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


@app.get("/api/cameras")
async def list_cameras():
    """List available camera devices."""
    cameras = camera_manager.list_available_cameras()
    return {"cameras": cameras}


@app.get("/api/sessions")
async def list_sessions():
    """List all active sessions."""
    sessions = session_manager.list_sessions()
    return {"sessions": [s.to_dict() for s in sessions]}


@app.post("/api/sessions")
async def create_session(request: CreateSessionRequest):
    """Create a new capture session."""
    camera = camera_manager.acquire_camera(request.camera_index)
    if camera is None:
        raise HTTPException(status_code=400, detail="Failed to open camera")
    
    session = session_manager.create_session(request.camera_index, request.camera_name)
    start_session_ocr(session)
    
    return session.to_dict()


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session details."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.to_dict()


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and release the camera."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    ocr_manager.stop_ocr(session_id)
    camera_manager.release_camera(session.camera_index)
    session_manager.delete_session(session_id)
    
    return {"status": "deleted"}


@app.put("/api/sessions/{session_id}/perspective")
async def update_perspective(session_id: str, request: PerspectiveRequest):
    """Update perspective correction points and output size."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    points = None
    if request.points and len(request.points) == 4:
        points = [(p[0], p[1]) for p in request.points]
    
    output_size = None
    if request.output_size and len(request.output_size) == 2:
        output_size = tuple(request.output_size)
    
    session_manager.update_perspective(session_id, points, output_size)
    updated = session_manager.get_session(session_id)
    return {
        "status": "updated", 
        "perspective_points": updated.perspective_points,
        "perspective_output_size": list(updated.perspective_output_size)
    }


@app.post("/api/sessions/{session_id}/color-filters")
async def add_color_filter(session_id: str, request: ColorFilterRequest):
    """Add a new color filter."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    cf = session_manager.add_color_filter(session_id, request.bgr, request.tolerance)
    if cf is None:
        raise HTTPException(status_code=400, detail="Failed to add color filter")
    
    return cf.to_dict()


@app.put("/api/sessions/{session_id}/color-filters/{filter_id}")
async def update_color_filter(session_id: str, filter_id: str, request: ColorFilterUpdateRequest):
    """Update a color filter's tolerance."""
    if not session_manager.update_color_filter(session_id, filter_id, request.tolerance):
        raise HTTPException(status_code=404, detail="Session or filter not found")
    
    return {"status": "updated"}


@app.delete("/api/sessions/{session_id}/color-filters/{filter_id}")
async def delete_color_filter(session_id: str, filter_id: str):
    """Delete a color filter."""
    if not session_manager.delete_color_filter(session_id, filter_id):
        raise HTTPException(status_code=404, detail="Session or filter not found")
    
    return {"status": "deleted"}


@app.delete("/api/sessions/{session_id}/color-filters")
async def clear_color_filters(session_id: str):
    """Clear all color filters."""
    if not session_manager.clear_color_filters(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {"status": "cleared"}


@app.put("/api/sessions/{session_id}/morphology")
async def update_morphology(session_id: str, request: MorphologyRequest):
    """Update morphology settings."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session_manager.update_morphology(session_id, request.erosion_kernel, request.dilation_kernel)
    updated = session_manager.get_session(session_id)
    return {
        "status": "updated",
        "erosion_kernel": updated.erosion_kernel,
        "dilation_kernel": updated.dilation_kernel
    }


@app.post("/api/sessions/{session_id}/pick-color")
async def pick_color(session_id: str, request: PickColorRequest):
    """Pick a color from the perspective-corrected frame at given coordinates."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    camera = camera_manager.get_camera(session.camera_index)
    if camera is None:
        raise HTTPException(status_code=400, detail="Camera not available")
    
    frame = camera.get_frame()
    if frame is None:
        raise HTTPException(status_code=400, detail="No frame available")
    
    perspective_frame = process_frame_perspective(
        frame, 
        session.perspective_points,
        session.perspective_output_size
    )
    
    bgr = get_color_at_point(perspective_frame, request.x, request.y)
    
    return {"bgr": bgr}


@app.post("/api/sessions/{session_id}/ocr-regions")
async def add_ocr_region(session_id: str, request: OcrRegionRequest):
    """Add an OCR region."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    region = session_manager.add_ocr_region(
        session_id, request.x, request.y, request.width, request.height, request.label
    )
    if region is None:
        raise HTTPException(status_code=400, detail="Failed to add OCR region")
    
    return region.to_dict()


@app.put("/api/sessions/{session_id}/ocr-regions/{region_id}")
async def update_ocr_region(session_id: str, region_id: str, request: OcrRegionUpdateRequest):
    """Update an OCR region."""
    if not session_manager.update_ocr_region(
        session_id, region_id, request.x, request.y, request.width, request.height, 
        request.label, request.ocr_backend
    ):
        raise HTTPException(status_code=400, detail="Session/region not found or name already exists")
    
    return {"status": "updated"}


@app.delete("/api/sessions/{session_id}/ocr-regions/{region_id}")
async def delete_ocr_region(session_id: str, region_id: str):
    """Delete an OCR region."""
    if not session_manager.delete_ocr_region(session_id, region_id):
        raise HTTPException(status_code=404, detail="Session or region not found")
    
    return {"status": "deleted"}


@app.delete("/api/sessions/{session_id}/ocr-regions")
async def clear_ocr_regions(session_id: str):
    """Clear all OCR regions."""
    if not session_manager.clear_ocr_regions(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {"status": "cleared"}


# ============= Glyph Management =============

class GlyphRequest(BaseModel):
    char: str
    template: list[list[int]]
    width: int
    height: int


class GlyphUpdateRequest(BaseModel):
    char: str


@app.get("/api/sessions/{session_id}/glyphs")
async def list_glyphs(session_id: str):
    """List all glyphs for a session."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {"glyphs": [g.to_dict() for g in session.glyphs]}


@app.post("/api/sessions/{session_id}/glyphs")
async def add_glyph(session_id: str, request: GlyphRequest):
    """Add a new glyph template."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    glyph = session_manager.add_glyph(
        session_id, request.char, request.template, request.width, request.height
    )
    if glyph is None:
        raise HTTPException(status_code=400, detail="Failed to add glyph")
    
    return glyph.to_dict()


@app.put("/api/sessions/{session_id}/glyphs/{glyph_id}")
async def update_glyph(session_id: str, glyph_id: str, request: GlyphUpdateRequest):
    """Update a glyph's character label."""
    if not session_manager.update_glyph(session_id, glyph_id, request.char):
        raise HTTPException(status_code=404, detail="Session or glyph not found")
    
    return {"status": "updated"}


@app.delete("/api/sessions/{session_id}/glyphs/{glyph_id}")
async def delete_glyph(session_id: str, glyph_id: str):
    """Delete a glyph."""
    if not session_manager.delete_glyph(session_id, glyph_id):
        raise HTTPException(status_code=404, detail="Session or glyph not found")
    
    return {"status": "deleted"}


@app.delete("/api/sessions/{session_id}/glyphs")
async def clear_glyphs(session_id: str):
    """Clear all glyphs."""
    if not session_manager.clear_glyphs(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {"status": "cleared"}


@app.get("/api/sessions/{session_id}/detect-glyphs")
async def detect_glyphs(session_id: str, region_id: Optional[str] = None, 
                        merge_vertical: bool = False):
    """
    Detect glyphs in the current processed frame for training.
    Returns detected glyphs with their templates for labeling.
    
    Args:
        session_id: Session ID
        region_id: Optional region to crop to
        merge_vertical: If True, auto-merge vertically stacked glyphs (like ':')
    """
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    camera = camera_manager.get_camera(session.camera_index)
    if camera is None:
        raise HTTPException(status_code=400, detail="Camera not available")
    
    frame = camera.get_frame()
    if frame is None:
        raise HTTPException(status_code=400, detail="No frame available")
    
    # Get processed frame
    processed = process_frame_full(
        frame,
        perspective_points=session.perspective_points,
        output_size=session.perspective_output_size,
        color_filters=[cf.to_dict() for cf in session.color_filters],
        erosion_kernel=session.erosion_kernel,
        dilation_kernel=session.dilation_kernel
    )
    
    # If region specified, crop to that region
    if region_id:
        region = next((r for r in session.ocr_regions if r.id == region_id), None)
        if region:
            h, w = processed.shape[:2]
            x1 = max(0, min(region.x, w))
            y1 = max(0, min(region.y, h))
            x2 = max(0, min(region.x + region.width, w))
            y2 = max(0, min(region.y + region.height, h))
            processed = processed[y1:y2, x1:x2]
    
    # Detect glyphs
    detected = get_detected_glyphs_for_training(processed, merge_vertical=merge_vertical)
    
    return {
        "glyphs": detected,
        "glyph_size": GLYPH_SIZE,
        "merge_vertical": merge_vertical
    }


class CombineGlyphsRequest(BaseModel):
    indices: list[int]
    region_id: Optional[str] = None


@app.post("/api/sessions/{session_id}/combine-glyphs")
async def combine_glyphs(session_id: str, request: CombineGlyphsRequest):
    """
    Combine multiple detected glyphs into a single template.
    Used for characters like ':' that are detected as separate components.
    """
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    camera = camera_manager.get_camera(session.camera_index)
    if camera is None:
        raise HTTPException(status_code=400, detail="Camera not available")
    
    frame = camera.get_frame()
    if frame is None:
        raise HTTPException(status_code=400, detail="No frame available")
    
    # Get processed frame
    processed = process_frame_full(
        frame,
        perspective_points=session.perspective_points,
        output_size=session.perspective_output_size,
        color_filters=[cf.to_dict() for cf in session.color_filters],
        erosion_kernel=session.erosion_kernel,
        dilation_kernel=session.dilation_kernel
    )
    
    # If region specified, crop to that region
    if request.region_id:
        region = next((r for r in session.ocr_regions if r.id == request.region_id), None)
        if region:
            h, w = processed.shape[:2]
            x1 = max(0, min(region.x, w))
            y1 = max(0, min(region.y, h))
            x2 = max(0, min(region.x + region.width, w))
            y2 = max(0, min(region.y + region.height, h))
            processed = processed[y1:y2, x1:x2]
    
    combined = combine_glyphs_by_indices(processed, request.indices)
    
    if combined is None:
        raise HTTPException(status_code=400, detail="Invalid glyph indices")
    
    return combined


def generate_mjpeg_stream(session_id: str, stream_type: str):
    """Generator for MJPEG streaming."""
    while True:
        session = session_manager.get_session(session_id)
        if session is None:
            break
        
        camera = camera_manager.get_camera(session.camera_index)
        if camera is None:
            break
        
        frame = camera.get_frame()
        if frame is None:
            continue
        
        if stream_type == "original":
            pass
        elif stream_type == "perspective":
            frame = process_frame_perspective(
                frame,
                session.perspective_points,
                session.perspective_output_size
            )
        elif stream_type == "processed":
            frame = process_frame_full(
                frame,
                perspective_points=session.perspective_points,
                output_size=session.perspective_output_size,
                color_filters=[cf.to_dict() for cf in session.color_filters],
                erosion_kernel=session.erosion_kernel,
                dilation_kernel=session.dilation_kernel
            )
        
        jpeg = frame_to_jpeg(frame)
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        )


@app.get("/stream/{session_id}/original")
async def stream_original(session_id: str):
    """MJPEG stream of original camera feed."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return StreamingResponse(
        generate_mjpeg_stream(session_id, "original"),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/stream/{session_id}/perspective")
async def stream_perspective(session_id: str):
    """MJPEG stream with perspective correction applied."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return StreamingResponse(
        generate_mjpeg_stream(session_id, "perspective"),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/stream/{session_id}/processed")
async def stream_processed(session_id: str):
    """MJPEG stream with full processing (perspective + color/morphology)."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return StreamingResponse(
        generate_mjpeg_stream(session_id, "processed"),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.websocket("/ws/{session_id}/ocr")
async def websocket_ocr(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time OCR results."""
    session = session_manager.get_session(session_id)
    if session is None:
        await websocket.close(code=4004)
        return
    
    await websocket.accept()
    
    queue: asyncio.Queue = asyncio.Queue()
    
    def on_ocr_result(results: dict[str, list[dict]]):
        try:
            queue.put_nowait(results)
        except asyncio.QueueFull:
            pass
    
    ocr_manager.subscribe(session_id, on_ocr_result)
    
    try:
        while True:
            try:
                results = await asyncio.wait_for(queue.get(), timeout=5.0)
                await websocket.send_text(json.dumps({"results": results}))
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"ping": True}))
    except WebSocketDisconnect:
        pass
    finally:
        ocr_manager.unsubscribe(session_id, on_ocr_result)


from fastapi.responses import PlainTextResponse


@app.get("/ocr/{session_id}")
async def get_ocr_results(session_id: str):
    """Get all OCR results for a session as JSON."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    results = ocr_manager.get_results(session_id)
    
    # Build region -> backend mapping
    region_backends = {r.label: r.ocr_backend for r in session.ocr_regions}
    
    formatted = {}
    for region_name, detections in results.items():
        texts = [d['text'] for d in detections]
        # Ensure all numeric values are Python native types for JSON serialization
        clean_detections = []
        for d in detections:
            clean_detections.append({
                "bbox": d.get("bbox", []),
                "text": d.get("text", ""),
                "confidence": float(d.get("confidence", 0))
            })
        formatted[region_name] = {
            "text": ' '.join(texts),
            "backend": region_backends.get(region_name, "tesseract"),
            "detections": clean_detections
        }
    
    return formatted


@app.get("/ocr/{session_id}/{region_name}", response_class=PlainTextResponse)
async def get_ocr_region_text(session_id: str, region_name: str):
    """Get plain text OCR result for a specific region."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    text = ocr_manager.get_region_text(session_id, region_name)
    if text is None:
        raise HTTPException(status_code=404, detail="Region not found or no results")
    
    return text


DEBUG_DIR = "./debug"


@app.get("/debug/{session_id}")
async def list_debug_images(session_id: str):
    """List all debug images for a session."""
    session = session_manager.get_session(session_id)
    if session is None:
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
    return parser.parse_args()


def open_browser(host: str, port: int):
    """Open the default browser to the app URL."""
    import webbrowser
    import threading
    import time
    
    def _open():
        time.sleep(1.5)  # Wait for server to start
        url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}"
        webbrowser.open(url)
        print(f"Opened browser at {url}")
    
    threading.Thread(target=_open, daemon=True).start()


if __name__ == "__main__":
    import uvicorn
    
    args = parse_args()
    
    # Setup static files for production
    has_static = setup_static_files()
    
    print(f"Starting OCR Camera Backend...")
    print(f"Host: {args.host}")
    print(f"Port: {args.port}")
    print(f"Static files: {'Yes' if has_static else 'No (run frontend dev server separately)'}")
    
    # Open browser if static files available and not disabled
    if has_static and not args.no_browser:
        open_browser(args.host, args.port)
    
    uvicorn.run(app, host=args.host, port=args.port)
