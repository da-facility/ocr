"""
Worker process that handles camera capture, image processing, and OCR.

This runs in a separate process from the FastAPI webserver to prevent
camera/ML operations from blocking HTTP requests.
"""
import multiprocessing as mp
from multiprocessing.connection import Connection
import sys
import os
import threading
import time
from typing import Optional, Callable
import numpy as np

# Add parent directory to path for imports when running as subprocess
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ipc import IPCServer, IPCMessage, IPCResponse, Command
from camera import camera_manager, CameraManager
from sessions import session_manager, SessionManager
from processing import process_frame_perspective, process_frame_full, frame_to_jpeg, get_color_at_point
from ocr import ocr_manager, OCRManager
from glyphs import get_detected_glyphs_for_training, combine_glyphs_by_indices, GLYPH_SIZE


class WorkerState:
    """Shared state for the worker process."""
    
    def __init__(self):
        self.camera_manager = camera_manager
        self.session_manager = session_manager
        self.ocr_manager = ocr_manager
        
        # OCR result callbacks for streaming to clients
        self.ocr_callbacks: dict[str, list[Callable]] = {}
        self.ocr_lock = threading.Lock()


def start_session_ocr(state: WorkerState, session):
    """Helper to start OCR for a session."""
    def get_processed_frame():
        sess = state.session_manager.get_session(session.id)
        if sess is None:
            return None
        cam = state.camera_manager.get_camera(sess.camera_index)
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
        sess = state.session_manager.get_session(session.id)
        if sess is None:
            return []
        return [r.to_dict() for r in sess.ocr_regions]
    
    def get_glyphs():
        sess = state.session_manager.get_session(session.id)
        if sess is None:
            return []
        return [g.to_dict() for g in sess.glyphs]
    
    state.ocr_manager.start_ocr(session.id, get_processed_frame, get_regions, get_glyphs)


def register_handlers(server: IPCServer, state: WorkerState):
    """Register all command handlers."""
    
    # ============= Camera handlers =============
    
    def handle_list_cameras():
        return state.camera_manager.list_available_cameras()
    
    def handle_acquire_camera(camera_index: int):
        camera = state.camera_manager.acquire_camera(camera_index)
        return camera is not None
    
    def handle_release_camera(camera_index: int):
        state.camera_manager.release_camera(camera_index)
        return True
    
    def handle_get_frame(session_id: str):
        session = state.session_manager.get_session(session_id)
        if session is None:
            return None
        camera = state.camera_manager.get_camera(session.camera_index)
        if camera is None:
            return None
        return camera.get_frame()
    
    # ============= Session handlers =============
    
    def handle_create_session(camera_index: int, camera_name: str = ""):
        camera = state.camera_manager.acquire_camera(camera_index)
        if camera is None:
            return None
        
        session = state.session_manager.create_session(camera_index, camera_name)
        start_session_ocr(state, session)
        return session.to_dict()
    
    def handle_delete_session(session_id: str):
        session = state.session_manager.get_session(session_id)
        if session is None:
            return False
        
        state.ocr_manager.stop_ocr(session_id)
        state.camera_manager.release_camera(session.camera_index)
        state.session_manager.delete_session(session_id)
        return True
    
    def handle_get_session(session_id: str):
        session = state.session_manager.get_session(session_id)
        if session is None:
            return None
        return session.to_dict()
    
    def handle_list_sessions():
        sessions = state.session_manager.list_sessions()
        return [s.to_dict() for s in sessions]
    
    def handle_update_perspective(session_id: str, points: Optional[list] = None, 
                                   output_size: Optional[list] = None):
        session = state.session_manager.get_session(session_id)
        if session is None:
            return None
        
        parsed_points = None
        if points and len(points) == 4:
            parsed_points = [(p[0], p[1]) for p in points]
        
        parsed_size = None
        if output_size and len(output_size) == 2:
            parsed_size = tuple(output_size)
        
        state.session_manager.update_perspective(session_id, parsed_points, parsed_size)
        updated = state.session_manager.get_session(session_id)
        return {
            "status": "updated",
            "perspective_points": updated.perspective_points,
            "perspective_output_size": list(updated.perspective_output_size)
        }
    
    def handle_add_color_filter(session_id: str, bgr: list, tolerance: list):
        cf = state.session_manager.add_color_filter(session_id, bgr, tolerance)
        if cf is None:
            return None
        return cf.to_dict()
    
    def handle_update_color_filter(session_id: str, filter_id: str, tolerance: list):
        return state.session_manager.update_color_filter(session_id, filter_id, tolerance)
    
    def handle_delete_color_filter(session_id: str, filter_id: str):
        return state.session_manager.delete_color_filter(session_id, filter_id)
    
    def handle_clear_color_filters(session_id: str):
        return state.session_manager.clear_color_filters(session_id)
    
    def handle_update_morphology(session_id: str, erosion_kernel: Optional[int] = None,
                                  dilation_kernel: Optional[int] = None):
        session = state.session_manager.get_session(session_id)
        if session is None:
            return None
        
        state.session_manager.update_morphology(session_id, erosion_kernel, dilation_kernel)
        updated = state.session_manager.get_session(session_id)
        return {
            "status": "updated",
            "erosion_kernel": updated.erosion_kernel,
            "dilation_kernel": updated.dilation_kernel
        }
    
    def handle_pick_color(session_id: str, x: int, y: int):
        session = state.session_manager.get_session(session_id)
        if session is None:
            return None
        
        camera = state.camera_manager.get_camera(session.camera_index)
        if camera is None:
            return None
        
        frame = camera.get_frame()
        if frame is None:
            return None
        
        perspective_frame = process_frame_perspective(
            frame,
            session.perspective_points,
            session.perspective_output_size
        )
        
        bgr = get_color_at_point(perspective_frame, x, y)
        return {"bgr": bgr}
    
    # ============= OCR Region handlers =============
    
    def handle_add_ocr_region(session_id: str, x: int, y: int, width: int, height: int, 
                               label: str = ""):
        region = state.session_manager.add_ocr_region(session_id, x, y, width, height, label)
        if region is None:
            return None
        return region.to_dict()
    
    def handle_update_ocr_region(session_id: str, region_id: str, 
                                  x: Optional[int] = None, y: Optional[int] = None,
                                  width: Optional[int] = None, height: Optional[int] = None,
                                  label: Optional[str] = None, ocr_backend: Optional[str] = None):
        return state.session_manager.update_ocr_region(
            session_id, region_id, x, y, width, height, label, ocr_backend
        )
    
    def handle_delete_ocr_region(session_id: str, region_id: str):
        return state.session_manager.delete_ocr_region(session_id, region_id)
    
    def handle_clear_ocr_regions(session_id: str):
        return state.session_manager.clear_ocr_regions(session_id)
    
    # ============= Glyph handlers =============
    
    def handle_list_glyphs(session_id: str):
        session = state.session_manager.get_session(session_id)
        if session is None:
            return None
        return [g.to_dict() for g in session.glyphs]
    
    def handle_add_glyph(session_id: str, char: str, template: list, width: int, height: int):
        glyph = state.session_manager.add_glyph(session_id, char, template, width, height)
        if glyph is None:
            return None
        return glyph.to_dict()
    
    def handle_update_glyph(session_id: str, glyph_id: str, char: str):
        return state.session_manager.update_glyph(session_id, glyph_id, char)
    
    def handle_delete_glyph(session_id: str, glyph_id: str):
        return state.session_manager.delete_glyph(session_id, glyph_id)
    
    def handle_clear_glyphs(session_id: str):
        return state.session_manager.clear_glyphs(session_id)
    
    def handle_detect_glyphs(session_id: str, region_id: Optional[str] = None,
                              merge_vertical: bool = False):
        session = state.session_manager.get_session(session_id)
        if session is None:
            return None
        
        camera = state.camera_manager.get_camera(session.camera_index)
        if camera is None:
            return None
        
        frame = camera.get_frame()
        if frame is None:
            return None
        
        processed = process_frame_full(
            frame,
            perspective_points=session.perspective_points,
            output_size=session.perspective_output_size,
            color_filters=[cf.to_dict() for cf in session.color_filters],
            erosion_kernel=session.erosion_kernel,
            dilation_kernel=session.dilation_kernel
        )
        
        if region_id:
            region = next((r for r in session.ocr_regions if r.id == region_id), None)
            if region:
                h, w = processed.shape[:2]
                x1 = max(0, min(region.x, w))
                y1 = max(0, min(region.y, h))
                x2 = max(0, min(region.x + region.width, w))
                y2 = max(0, min(region.y + region.height, h))
                processed = processed[y1:y2, x1:x2]
        
        detected = get_detected_glyphs_for_training(processed, merge_vertical=merge_vertical)
        
        return {
            "glyphs": detected,
            "glyph_size": GLYPH_SIZE,
            "merge_vertical": merge_vertical
        }
    
    def handle_combine_glyphs(session_id: str, indices: list, region_id: Optional[str] = None):
        session = state.session_manager.get_session(session_id)
        if session is None:
            return None
        
        camera = state.camera_manager.get_camera(session.camera_index)
        if camera is None:
            return None
        
        frame = camera.get_frame()
        if frame is None:
            return None
        
        processed = process_frame_full(
            frame,
            perspective_points=session.perspective_points,
            output_size=session.perspective_output_size,
            color_filters=[cf.to_dict() for cf in session.color_filters],
            erosion_kernel=session.erosion_kernel,
            dilation_kernel=session.dilation_kernel
        )
        
        if region_id:
            region = next((r for r in session.ocr_regions if r.id == region_id), None)
            if region:
                h, w = processed.shape[:2]
                x1 = max(0, min(region.x, w))
                y1 = max(0, min(region.y, h))
                x2 = max(0, min(region.x + region.width, w))
                y2 = max(0, min(region.y + region.height, h))
                processed = processed[y1:y2, x1:x2]
        
        return combine_glyphs_by_indices(processed, indices)
    
    # ============= OCR Result handlers =============
    
    def handle_get_ocr_results(session_id: str):
        session = state.session_manager.get_session(session_id)
        if session is None:
            return None
        
        results = state.ocr_manager.get_results(session_id)
        region_backends = {r.label: r.ocr_backend for r in session.ocr_regions}
        
        formatted = {}
        for region_name, detections in results.items():
            texts = [d['text'] for d in detections]
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
    
    def handle_get_region_text(session_id: str, region_name: str):
        return state.ocr_manager.get_region_text(session_id, region_name)
    
    # ============= Stream handlers =============
    
    def handle_get_stream_frame(session_id: str, stream_type: str = "processed"):
        session = state.session_manager.get_session(session_id)
        if session is None:
            return None
        
        camera = state.camera_manager.get_camera(session.camera_index)
        if camera is None:
            return None
        
        frame = camera.get_frame()
        if frame is None:
            return None
        
        if stream_type == "original":
            return frame
        elif stream_type == "perspective":
            return process_frame_perspective(
                frame,
                session.perspective_points,
                session.perspective_output_size
            )
        elif stream_type == "processed":
            return process_frame_full(
                frame,
                perspective_points=session.perspective_points,
                output_size=session.perspective_output_size,
                color_filters=[cf.to_dict() for cf in session.color_filters],
                erosion_kernel=session.erosion_kernel,
                dilation_kernel=session.dilation_kernel
            )
        return frame
    
    # ============= Control handlers =============
    
    def handle_ping():
        return "pong"
    
    # Register all handlers
    server.register_handler(Command.LIST_CAMERAS, handle_list_cameras)
    server.register_handler(Command.ACQUIRE_CAMERA, handle_acquire_camera)
    server.register_handler(Command.RELEASE_CAMERA, handle_release_camera)
    server.register_handler(Command.GET_FRAME, handle_get_frame)
    
    server.register_handler(Command.CREATE_SESSION, handle_create_session)
    server.register_handler(Command.DELETE_SESSION, handle_delete_session)
    server.register_handler(Command.GET_SESSION, handle_get_session)
    server.register_handler(Command.LIST_SESSIONS, handle_list_sessions)
    server.register_handler(Command.UPDATE_PERSPECTIVE, handle_update_perspective)
    server.register_handler(Command.ADD_COLOR_FILTER, handle_add_color_filter)
    server.register_handler(Command.UPDATE_COLOR_FILTER, handle_update_color_filter)
    server.register_handler(Command.DELETE_COLOR_FILTER, handle_delete_color_filter)
    server.register_handler(Command.CLEAR_COLOR_FILTERS, handle_clear_color_filters)
    server.register_handler(Command.UPDATE_MORPHOLOGY, handle_update_morphology)
    server.register_handler(Command.PICK_COLOR, handle_pick_color)
    
    server.register_handler(Command.ADD_OCR_REGION, handle_add_ocr_region)
    server.register_handler(Command.UPDATE_OCR_REGION, handle_update_ocr_region)
    server.register_handler(Command.DELETE_OCR_REGION, handle_delete_ocr_region)
    server.register_handler(Command.CLEAR_OCR_REGIONS, handle_clear_ocr_regions)
    
    server.register_handler(Command.LIST_GLYPHS, handle_list_glyphs)
    server.register_handler(Command.ADD_GLYPH, handle_add_glyph)
    server.register_handler(Command.UPDATE_GLYPH, handle_update_glyph)
    server.register_handler(Command.DELETE_GLYPH, handle_delete_glyph)
    server.register_handler(Command.CLEAR_GLYPHS, handle_clear_glyphs)
    server.register_handler(Command.DETECT_GLYPHS, handle_detect_glyphs)
    server.register_handler(Command.COMBINE_GLYPHS, handle_combine_glyphs)
    
    server.register_handler(Command.GET_OCR_RESULTS, handle_get_ocr_results)
    server.register_handler(Command.GET_REGION_TEXT, handle_get_region_text)
    
    server.register_handler(Command.GET_STREAM_FRAME, handle_get_stream_frame)
    
    server.register_handler(Command.PING, handle_ping)


def worker_main(conn: Connection):
    """Main entry point for the worker process."""
    print("[Worker] Starting ML/Camera worker process...")
    
    # Initialize state
    state = WorkerState()
    
    # Restore sessions and start their OCR
    print("[Worker] Restoring sessions...")
    for session in state.session_manager.list_sessions():
        camera = state.camera_manager.acquire_camera(session.camera_index)
        if camera:
            start_session_ocr(state, session)
            print(f"[Worker] Restored session {session.id} with camera {session.camera_index}")
        else:
            print(f"[Worker] Failed to restore session {session.id}: camera {session.camera_index} not available")
    
    # Create and configure IPC server
    server = IPCServer(conn)
    register_handlers(server, state)
    
    print("[Worker] Worker ready, starting IPC server loop...")
    
    try:
        server.run()
    except KeyboardInterrupt:
        print("[Worker] Interrupted, shutting down...")
    except Exception as e:
        print(f"[Worker] Error: {e}")
    finally:
        print("[Worker] Shutting down...")
        # Cleanup: stop all OCR workers and release cameras
        for session in state.session_manager.list_sessions():
            state.ocr_manager.stop_ocr(session.id)
            state.camera_manager.release_camera(session.camera_index)
        print("[Worker] Shutdown complete")


def start_worker_process() -> tuple[mp.Process, Connection]:
    """Start the worker process and return (process, client_connection)."""
    # Create IPC pipe
    parent_conn, child_conn = mp.Pipe()
    
    # Start worker process
    process = mp.Process(target=worker_main, args=(child_conn,), daemon=True)
    process.start()
    
    return process, parent_conn


if __name__ == "__main__":
    # For testing: run worker directly with stdin/stdout IPC
    import pickle
    
    # Create a simple pipe simulation for testing
    parent_conn, child_conn = mp.Pipe()
    worker_main(child_conn)
