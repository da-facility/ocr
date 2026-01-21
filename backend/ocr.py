import threading
import time
import os
from typing import Optional, Callable
import numpy as np
import cv2

from glyphs import recognize_with_glyphs, glyphs_to_text


DEBUG_DIR = "./debug"


def ensure_debug_dir(session_id: str):
    """Create debug directory for a session if it doesn't exist."""
    path = os.path.join(DEBUG_DIR, session_id)
    os.makedirs(path, exist_ok=True)
    return path


def save_debug_image(session_id: str, region_name: str, image: np.ndarray):
    """Save a debug image for a region."""
    path = ensure_debug_dir(session_id)
    safe_name = region_name.replace("/", "_").replace(" ", "_")
    filepath = os.path.join(path, f"{safe_name}.png")
    cv2.imwrite(filepath, image)


class OCREngine:
    """OCR Engine using glyph template matching."""
    _instance: Optional['OCREngine'] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        print("OCR Engine initialized (glyph-based)")

    def read_text(self, frame: np.ndarray, backend: str = "glyphs", 
                  session_id: str = "", region_name: str = "",
                  glyph_templates: Optional[list[dict]] = None) -> list[dict]:
        """
        Run OCR on a frame and return detected text.
        Input should be a binary image (black #000000 and white #ffffff).
        Uses glyph template matching.
        """
        try:
            if session_id and region_name:
                save_debug_image(session_id, region_name, frame)
            
            return self._read_glyphs(frame, glyph_templates or [])
        except Exception as e:
            print(f"OCR error: {e}")
            return []

    def _read_glyphs(self, frame: np.ndarray, templates: list[dict]) -> list[dict]:
        """Use glyph template matching for OCR."""
        if not templates:
            return []
        
        results = recognize_with_glyphs(frame, templates)
        text = glyphs_to_text(results)
        
        if text and text != '?' * len(text):
            avg_conf = sum(float(r['confidence']) for r in results) / len(results) if results else 0.0
            return [{
                "bbox": [],
                "text": text,
                "confidence": float(avg_conf)  # Ensure Python float for JSON serialization
            }]
        return []


class OCRWorker:
    def __init__(self, session_id: str, 
                 get_frame_fn: Callable[[], Optional[np.ndarray]],
                 get_regions_fn: Callable[[], list[dict]],
                 get_glyphs_fn: Callable[[], list[dict]],
                 on_result: Callable[[str, dict[str, list[dict]]], None]):
        self.session_id = session_id
        self.get_frame_fn = get_frame_fn
        self.get_regions_fn = get_regions_fn
        self.get_glyphs_fn = get_glyphs_fn
        self.on_result = on_result
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.ocr_engine = OCREngine()
        self.fps_limit = 2.0

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._ocr_loop, daemon=True)
        self.thread.start()

    def _ocr_loop(self):
        interval = 1.0 / self.fps_limit
        while self.running:
            start_time = time.time()
            
            frame = self.get_frame_fn()
            if frame is not None:
                regions = self.get_regions_fn()
                glyph_templates = self.get_glyphs_fn()
                results_by_region = {}
                
                if regions:
                    for region in regions:
                        x, y = region['x'], region['y']
                        w, h = region['width'], region['height']
                        label = region['label']
                        backend = region.get('ocr_backend', 'tesseract')
                        
                        h_frame, w_frame = frame.shape[:2]
                        x = max(0, min(x, w_frame))
                        y = max(0, min(y, h_frame))
                        x2 = max(0, min(x + w, w_frame))
                        y2 = max(0, min(y + h, h_frame))
                        
                        if x2 > x and y2 > y:
                            cropped = frame[y:y2, x:x2]
                            region_results = self.ocr_engine.read_text(
                                cropped, 
                                backend=backend,
                                session_id=self.session_id,
                                region_name=label,
                                glyph_templates=glyph_templates
                            )
                            results_by_region[label] = region_results
                else:
                    full_results = self.ocr_engine.read_text(
                        frame, 
                        backend="tesseract",
                        session_id=self.session_id,
                        region_name="_full",
                        glyph_templates=glyph_templates
                    )
                    results_by_region['_full'] = full_results
                
                self.on_result(self.session_id, results_by_region)
            
            elapsed = time.time() - start_time
            sleep_time = max(0, interval - elapsed)
            time.sleep(sleep_time)

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)


class OCRManager:
    def __init__(self):
        self.workers: dict[str, OCRWorker] = {}
        self.callbacks: dict[str, list[Callable[[dict[str, list[dict]]], None]]] = {}
        self.latest_results: dict[str, dict[str, list[dict]]] = {}
        self.lock = threading.Lock()

    def start_ocr(self, session_id: str, 
                  get_frame_fn: Callable[[], Optional[np.ndarray]],
                  get_regions_fn: Callable[[], list[dict]],
                  get_glyphs_fn: Callable[[], list[dict]]):
        with self.lock:
            if session_id in self.workers:
                return
            
            worker = OCRWorker(
                session_id=session_id,
                get_frame_fn=get_frame_fn,
                get_regions_fn=get_regions_fn,
                get_glyphs_fn=get_glyphs_fn,
                on_result=self._handle_result
            )
            self.workers[session_id] = worker
            self.latest_results[session_id] = {}
            worker.start()

    def stop_ocr(self, session_id: str):
        with self.lock:
            if session_id in self.workers:
                self.workers[session_id].stop()
                del self.workers[session_id]
            if session_id in self.callbacks:
                del self.callbacks[session_id]
            if session_id in self.latest_results:
                del self.latest_results[session_id]

    def subscribe(self, session_id: str, callback: Callable[[dict[str, list[dict]]], None]):
        with self.lock:
            if session_id not in self.callbacks:
                self.callbacks[session_id] = []
            self.callbacks[session_id].append(callback)

    def unsubscribe(self, session_id: str, callback: Callable[[dict[str, list[dict]]], None]):
        with self.lock:
            if session_id in self.callbacks:
                try:
                    self.callbacks[session_id].remove(callback)
                except ValueError:
                    pass

    def get_results(self, session_id: str) -> dict[str, list[dict]]:
        with self.lock:
            return self.latest_results.get(session_id, {}).copy()

    def get_region_result(self, session_id: str, region_name: str) -> Optional[list[dict]]:
        with self.lock:
            results = self.latest_results.get(session_id, {})
            return results.get(region_name)

    def get_region_text(self, session_id: str, region_name: str) -> Optional[str]:
        results = self.get_region_result(session_id, region_name)
        if results is None:
            return None
        texts = [r['text'] for r in results]
        return ' '.join(texts)

    def _handle_result(self, session_id: str, results: dict[str, list[dict]]):
        with self.lock:
            self.latest_results[session_id] = results
            callbacks = self.callbacks.get(session_id, [])[:]
        
        for callback in callbacks:
            try:
                callback(results)
            except Exception as e:
                print(f"OCR callback error: {e}")


ocr_manager = OCRManager()
