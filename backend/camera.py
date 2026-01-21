import cv2
import threading
import time
from typing import Optional
import numpy as np
import platform
from cv2_enumerate_cameras import enumerate_cameras


def _open_video_capture(index: int) -> cv2.VideoCapture:
    if platform.system() == "Windows":
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
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

    @staticmethod
    def list_available_cameras(max_cameras: int = 10) -> list[dict]:
        """List available cameras using cv2_enumerate_cameras without opening devices."""
        available = []
        for info in enumerate_cameras():
            name = info.name or f"Camera {info.index + 1:02d}"
            available.append(
                {
                    "index": info.index,
                    "name": name,
                    "vid": info.vid,
                    "pid": info.pid,
                    "resolution": "",
                }
            )
        return available


camera_manager = CameraManager()
