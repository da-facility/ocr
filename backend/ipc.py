"""
IPC protocol for communication between the FastAPI webserver and the ML/camera worker process.

Uses multiprocessing Pipe for commands and shared memory for frames to avoid serialization overhead.
"""
import multiprocessing as mp
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from multiprocessing.connection import Connection
from typing import Any

import numpy as np


class Command(Enum):
    """Commands that can be sent to the worker."""
    # Camera commands
    LIST_CAMERAS = "list_cameras"
    REFRESH_CAMERAS = "refresh_cameras"
    ACQUIRE_CAMERA = "acquire_camera"
    RELEASE_CAMERA = "release_camera"
    GET_FRAME = "get_frame"
    
    # Session commands  
    CREATE_SESSION = "create_session"
    DELETE_SESSION = "delete_session"
    GET_SESSION = "get_session"
    LIST_SESSIONS = "list_sessions"
    UPDATE_PERSPECTIVE = "update_perspective"
    ADD_COLOR_FILTER = "add_color_filter"
    UPDATE_COLOR_FILTER = "update_color_filter"
    DELETE_COLOR_FILTER = "delete_color_filter"
    CLEAR_COLOR_FILTERS = "clear_color_filters"
    UPDATE_MORPHOLOGY = "update_morphology"
    PICK_COLOR = "pick_color"
    
    # OCR region commands
    ADD_OCR_REGION = "add_ocr_region"
    UPDATE_OCR_REGION = "update_ocr_region"
    DELETE_OCR_REGION = "delete_ocr_region"
    CLEAR_OCR_REGIONS = "clear_ocr_regions"
    RESET_REGION_VALIDATOR = "reset_region_validator"
    
    # Glyph commands
    LIST_GLYPHS = "list_glyphs"
    ADD_GLYPH = "add_glyph"
    UPDATE_GLYPH = "update_glyph"
    DELETE_GLYPH = "delete_glyph"
    CLEAR_GLYPHS = "clear_glyphs"
    DETECT_GLYPHS = "detect_glyphs"
    COMBINE_GLYPHS = "combine_glyphs"
    
    # Global glyph storage commands
    LIST_GLYPH_SETS = "list_glyph_sets"
    GET_GLYPH_SET = "get_glyph_set"
    CREATE_GLYPH_SET = "create_glyph_set"
    DELETE_GLYPH_SET = "delete_glyph_set"
    EXPORT_GLYPHS = "export_glyphs"
    IMPORT_GLYPHS = "import_glyphs"
    
    # OCR commands
    GET_OCR_RESULTS = "get_ocr_results"
    GET_REGION_TEXT = "get_region_text"
    SUBSCRIBE_OCR = "subscribe_ocr"
    UNSUBSCRIBE_OCR = "unsubscribe_ocr"
    
    # Stream commands
    GET_STREAM_FRAME = "get_stream_frame"
    
    # Control
    PING = "ping"
    SHUTDOWN = "shutdown"


@dataclass
class IPCMessage:
    """A message sent over IPC."""
    command: Command
    args: dict = field(default_factory=dict)
    request_id: int = 0


@dataclass
class IPCResponse:
    """A response from the worker."""
    success: bool
    data: Any = None
    error: str | None = None
    request_id: int = 0


class FrameCache:
    """Thread-safe cache for video frames with staleness tracking."""
    
    def __init__(self, max_age_seconds: float = 2.0):
        self.frames: dict[str, tuple[np.ndarray, float]] = {}  # session_id -> (frame, timestamp)
        self.lock = threading.Lock()
        self.max_age = max_age_seconds
    
    def put(self, key: str, frame: np.ndarray):
        """Store a frame with current timestamp."""
        with self.lock:
            self.frames[key] = (frame.copy(), time.time())
    
    def get(self, key: str) -> tuple[np.ndarray | None, bool]:
        """Get a frame. Returns (frame, is_stale). Returns (None, True) if no frame."""
        with self.lock:
            if key not in self.frames:
                return None, True
            frame, timestamp = self.frames[key]
            is_stale = (time.time() - timestamp) > self.max_age
            return frame.copy(), is_stale
    
    def remove(self, key: str):
        """Remove a cached frame."""
        with self.lock:
            self.frames.pop(key, None)
    
    def clear(self):
        """Clear all cached frames."""
        with self.lock:
            self.frames.clear()


class ResultCache:
    """Thread-safe cache for OCR results with staleness tracking."""
    
    def __init__(self, max_age_seconds: float = 5.0):
        self.results: dict[str, tuple[dict, float]] = {}  # session_id -> (results, timestamp)
        self.lock = threading.Lock()
        self.max_age = max_age_seconds
    
    def put(self, session_id: str, results: dict):
        """Store results with current timestamp."""
        with self.lock:
            self.results[session_id] = (results.copy(), time.time())
    
    def get(self, session_id: str) -> tuple[dict | None, bool]:
        """Get results. Returns (results, is_stale). Returns (None, True) if no results."""
        with self.lock:
            if session_id not in self.results:
                return None, True
            results, timestamp = self.results[session_id]
            is_stale = (time.time() - timestamp) > self.max_age
            return results.copy(), is_stale
    
    def remove(self, session_id: str):
        """Remove cached results."""
        with self.lock:
            self.results.pop(session_id, None)
    
    def clear(self):
        """Clear all cached results."""
        with self.lock:
            self.results.clear()


class IPCClient:
    """Client for sending commands to the worker process."""
    
    def __init__(self, conn: Connection, timeout: float = 1.0):
        self.conn = conn
        self.timeout = timeout
        self.lock = threading.Lock()
        self._request_counter = 0
        
        # Caches for frames and results
        self.frame_cache = FrameCache(max_age_seconds=2.0)
        self.result_cache = ResultCache(max_age_seconds=5.0)
    
    def _next_request_id(self) -> int:
        self._request_counter += 1
        return self._request_counter
    
    def send_command(self, command: Command, timeout: float | None = None, **kwargs) -> IPCResponse:
        """Send a command and wait for response with timeout."""
        if timeout is None:
            timeout = self.timeout

        request_id = self._next_request_id()
        msg = IPCMessage(command=command, args=kwargs, request_id=request_id)

        with self.lock:
            try:
                self.conn.send(msg)

                start_time = time.time()
                while True:
                    remaining = timeout - (time.time() - start_time)
                    if remaining <= 0:
                        return IPCResponse(success=False, error="Timeout waiting for response", request_id=request_id)

                    if self.conn.poll(remaining):
                        response = self.conn.recv()
                        if isinstance(response, IPCResponse):
                            # Check if this response matches our request
                            if response.request_id == request_id:
                                return response
                            # Stale response from a timed-out request, discard and keep waiting
                            print(
                                "[IPC] Discarding stale response "
                                f"(got id={response.request_id}, expected={request_id})"
                            )
                            continue
                        return IPCResponse(success=False, error="Invalid response type")
                    else:
                        return IPCResponse(success=False, error="Timeout waiting for response", request_id=request_id)
            except Exception as e:
                return IPCResponse(success=False, error=str(e), request_id=request_id)
    
    def ping(self) -> bool:
        """Check if worker is alive."""
        response = self.send_command(Command.PING, timeout=0.5)
        return response.success
    
    # Convenience methods with caching
    
    def get_frame(self, session_id: str, stream_type: str = "processed") -> tuple[np.ndarray | None, bool]:
        """
        Get a frame for streaming. Returns (frame, is_stale).
        Uses cache on timeout to avoid blocking.
        """
        cache_key = f"{session_id}:{stream_type}"
        
        response = self.send_command(
            Command.GET_STREAM_FRAME, 
            session_id=session_id, 
            stream_type=stream_type,
            timeout=0.5  # Short timeout for streaming
        )
        
        if response.success and response.data is not None:
            frame = response.data
            self.frame_cache.put(cache_key, frame)
            return frame, False
        
        # On timeout/error, return cached frame
        return self.frame_cache.get(cache_key)
    
    def get_ocr_results(self, session_id: str) -> tuple[dict | None, bool]:
        """
        Get OCR results. Returns (results, is_stale).
        Uses cache on timeout.
        """
        response = self.send_command(
            Command.GET_OCR_RESULTS,
            session_id=session_id,
            timeout=0.5
        )
        
        if response.success and response.data is not None:
            self.result_cache.put(session_id, response.data)
            return response.data, False
        
        return self.result_cache.get(session_id)
    
    def close(self):
        """Close the connection."""
        try:
            self.conn.close()
        except Exception:
            pass


class IPCServer:
    """Server side that handles commands in the worker process."""
    
    def __init__(self, conn: Connection):
        self.conn = conn
        self.running = False
        self.handlers: dict[Command, callable] = {}
    
    def register_handler(self, command: Command, handler: callable):
        """Register a handler for a command."""
        self.handlers[command] = handler
    
    def handle_message(self, msg: IPCMessage) -> IPCResponse:
        """Handle an incoming message and return response."""
        handler = self.handlers.get(msg.command)
        if handler is None:
            print(f"[IPC] Unknown command: {msg.command} (type: {type(msg.command)})")
            print(f"[IPC] Registered commands: {list(self.handlers.keys())}")
            return IPCResponse(
                success=False,
                error=f"Unknown command: {msg.command}",
                request_id=msg.request_id
            )

        try:
            result = handler(**msg.args)
            return IPCResponse(success=True, data=result, request_id=msg.request_id)
        except Exception as e:
            return IPCResponse(success=False, error=str(e), request_id=msg.request_id)
    
    def run(self):
        """Run the server loop."""
        self.running = True
        while self.running:
            try:
                if self.conn.poll(0.1):
                    msg = self.conn.recv()
                    if isinstance(msg, IPCMessage):
                        if msg.command == Command.SHUTDOWN:
                            self.running = False
                            self.conn.send(IPCResponse(success=True, request_id=msg.request_id))
                            break
                        
                        response = self.handle_message(msg)
                        self.conn.send(response)
            except EOFError:
                # Connection closed
                self.running = False
                break
            except Exception as e:
                print(f"IPC server error: {e}")
    
    def stop(self):
        """Stop the server loop."""
        self.running = False


def create_ipc_pair() -> tuple[Connection, Connection]:
    """Create a pair of connected IPC endpoints."""
    return mp.Pipe()
