import cv2
import threading
import time
from dataclasses import dataclass
from typing import Optional
import numpy as np
import platform
from cv2_enumerate_cameras import enumerate_cameras

# Use DirectShow on Windows for consistent camera enumeration
# This avoids duplicates from enumerating both MSMF and DirectShow
_CAMERA_BACKEND = cv2.CAP_DSHOW if platform.system() == "Windows" else None

# Cache duration for camera enumeration (seconds)
_CACHE_TTL = 5.0


@dataclass
class CameraInfo:
    """Stable camera identification using VID+PID."""
    index: int  # Current system index (may change)
    name: str  # Device name
    vid: Optional[int]  # USB Vendor ID (stable)
    pid: Optional[int]  # USB Product ID (stable)

    @property
    def stable_id(self) -> str:
        """Generate a stable identifier for this camera."""
        if self.vid is not None and self.pid is not None:
            return f"{self.vid:04x}:{self.pid:04x}"
        # Fallback to name-based ID if no VID/PID
        return f"name:{self.name}"

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "vid": self.vid,
            "pid": self.pid,
            "stable_id": self.stable_id,
            "resolution": "",
        }


class CameraEnumerator:
    """Cached camera enumeration for instant lookups."""

    def __init__(self):
        self._cache: list[CameraInfo] = []
        self._cache_time: float = 0
        self._lock = threading.Lock()

    def _enumerate(self) -> list[CameraInfo]:
        """Perform actual enumeration (called when cache is stale)."""
        cameras = enumerate_cameras(_CAMERA_BACKEND) if _CAMERA_BACKEND else enumerate_cameras()
        result = []
        for info in cameras:
            name = info.name or f"Camera {info.index + 1:02d}"
            result.append(CameraInfo(
                index=info.index,
                name=name,
                vid=info.vid,
                pid=info.pid,
            ))
        return result

    def list_cameras(self, force_refresh: bool = False) -> list[CameraInfo]:
        """List available cameras using cache when possible."""
        with self._lock:
            now = time.time()
            if force_refresh or (now - self._cache_time) > _CACHE_TTL or not self._cache:
                self._cache = self._enumerate()
                self._cache_time = now
            return list(self._cache)

    def refresh(self) -> list[CameraInfo]:
        """Force a cache refresh and return updated list."""
        return self.list_cameras(force_refresh=True)

    def find_by_stable_id(self, stable_id: str) -> Optional[CameraInfo]:
        """Find camera by its stable ID, returns current info with updated index."""
        cameras = self.list_cameras()
        for cam in cameras:
            if cam.stable_id == stable_id:
                return cam
        return None

    def find_by_vid_pid(self, vid: Optional[int], pid: Optional[int]) -> Optional[CameraInfo]:
        """Find camera by VID/PID combination."""
        if vid is None or pid is None:
            return None
        cameras = self.list_cameras()
        for cam in cameras:
            if cam.vid == vid and cam.pid == pid:
                return cam
        return None

    def find_by_name(self, name: str) -> Optional[CameraInfo]:
        """Find camera by name (fallback when VID/PID unavailable)."""
        cameras = self.list_cameras()
        for cam in cameras:
            if cam.name == name:
                return cam
        return None

    def resolve_index(self, vid: Optional[int], pid: Optional[int], name: str, fallback_index: int) -> int:
        """
        Resolve a camera to its current index using stable identifiers.

        Priority:
        1. VID+PID match (most stable)
        2. Name match (less stable but works for non-USB cameras)
        3. Original index (fallback)
        """
        # Try VID+PID first (most reliable)
        cam = self.find_by_vid_pid(vid, pid)
        if cam:
            return cam.index

        # Try name match
        cam = self.find_by_name(name)
        if cam:
            return cam.index

        # Fallback to original index
        return fallback_index


# Global enumerator instance
_enumerator = CameraEnumerator()


def _open_video_capture(index: int) -> cv2.VideoCapture:
    if _CAMERA_BACKEND is not None:
        cap = cv2.VideoCapture(index, _CAMERA_BACKEND)
        if cap.isOpened():
            return cap
    return cv2.VideoCapture(index)


def _read_frame_size(cap: cv2.VideoCapture) -> Optional[tuple[int, int]]:
    ret, frame = cap.read()
    if not ret or frame is None:
        return None
    height, width = frame.shape[:2]
    return width, height


def _try_set_resolution(cap: cv2.VideoCapture, sizes: list[tuple[int, int]]) -> Optional[tuple[int, int]]:
    for width, height in sizes:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        actual = _read_frame_size(cap)
        if actual == (width, height):
            return actual
    return _read_frame_size(cap)


class CameraCapture:
    def __init__(self, camera_index: int):
        self.camera_index = camera_index
        self.cap: Optional[cv2.VideoCapture] = None
        self.frame: Optional[np.ndarray] = None
        self.lock = threading.Lock()
        self.running = False
        self.thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        if self.running:
            return True
        
        self.cap = _open_video_capture(self.camera_index)
        if not self.cap.isOpened():
            return False

        _try_set_resolution(
            self.cap,
            [
                (1920, 1080),
                (1280, 720),
                (720, 576),
                (640, 480),
            ],
        )
        
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        return True

    def _capture_loop(self):
        while self.running:
            if self.cap is None:
                break
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.frame = frame
            time.sleep(0.01)

    def get_frame(self) -> Optional[np.ndarray]:
        with self.lock:
            if self.frame is not None:
                return self.frame.copy()
            return None

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
        if self.cap:
            self.cap.release()
            self.cap = None
        self.frame = None


class CameraManager:
    def __init__(self):
        self.cameras: dict[int, CameraCapture] = {}
        self.ref_counts: dict[int, int] = {}
        self.lock = threading.Lock()
        self.enumerator = _enumerator

    def acquire_camera(self, camera_index: int) -> Optional[CameraCapture]:
        with self.lock:
            if camera_index in self.cameras:
                self.ref_counts[camera_index] += 1
                return self.cameras[camera_index]

            camera = CameraCapture(camera_index)
            if camera.start():
                self.cameras[camera_index] = camera
                self.ref_counts[camera_index] = 1
                return camera
            return None

    def acquire_camera_by_id(
        self,
        vid: Optional[int],
        pid: Optional[int],
        name: str,
        fallback_index: int
    ) -> tuple[Optional[CameraCapture], int]:
        """
        Acquire camera using stable identifiers, resolving to current index.
        Returns (camera, resolved_index) tuple.
        """
        resolved_index = self.enumerator.resolve_index(vid, pid, name, fallback_index)
        camera = self.acquire_camera(resolved_index)
        return camera, resolved_index

    def release_camera(self, camera_index: int):
        with self.lock:
            if camera_index in self.ref_counts:
                self.ref_counts[camera_index] -= 1
                if self.ref_counts[camera_index] <= 0:
                    if camera_index in self.cameras:
                        self.cameras[camera_index].stop()
                        del self.cameras[camera_index]
                    del self.ref_counts[camera_index]

    def get_camera(self, camera_index: int) -> Optional[CameraCapture]:
        with self.lock:
            return self.cameras.get(camera_index)

    def list_available_cameras(self, force_refresh: bool = False) -> list[dict]:
        """List available cameras using cached enumeration (instant)."""
        cameras = self.enumerator.list_cameras(force_refresh=force_refresh)
        return [cam.to_dict() for cam in cameras]

    def refresh_cameras(self) -> list[dict]:
        """Force refresh camera list and return updated data."""
        cameras = self.enumerator.refresh()
        return [cam.to_dict() for cam in cameras]

    def get_camera_info(self, index: int) -> Optional[CameraInfo]:
        """Get camera info by current index."""
        cameras = self.enumerator.list_cameras()
        for cam in cameras:
            if cam.index == index:
                return cam
        return None


camera_manager = CameraManager()
