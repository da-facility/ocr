import cv2
import threading
import time
from typing import Optional
import numpy as np
import platform
import re
import subprocess


def _read_cmd_lines(command: list[str]) -> list[str]:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError:
        return []

    lines = []
    for line in result.stdout.splitlines():
        cleaned = line.strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def _get_system_camera_names() -> list[str]:
    system = platform.system()
    names: list[str] = []

    if system == "Windows":
        names = _read_cmd_lines(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-PnpDevice -Class Camera -Status OK | "
                "Select-Object -ExpandProperty FriendlyName",
            ]
        )
        if not names:
            names = _read_cmd_lines(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_PnPEntity | "
                    "Where-Object { $_.PNPClass -in @('Camera','Image') } | "
                    "Select-Object -ExpandProperty Name",
                ]
            )
    elif system == "Darwin":
        lines = _read_cmd_lines(["system_profiler", "SPCameraDataType"])
        for line in lines:
            match = re.match(r"^Model ID:\s*(.+)$", line)
            if match:
                names.append(match.group(1).strip())
    else:
        # Linux and others: fall back to OpenCV index naming.
        names = []

    return names


def _format_camera_name(index: int, system_names: list[str]) -> str:
    base = f"Camera {index + 1:02d}"
    if index < len(system_names):
        system_name = system_names[index].strip()
        if system_name and system_name.lower() != base.lower():
            return f"{base} - {system_name}"
    return base


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
        
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            return False
        
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        
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
        """List available cameras. Names are based on OpenCV index since 
        system_profiler and OpenCV don't index consistently."""
        available = []
        system_names = _get_system_camera_names()
        
        for i in range(max_cameras):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                
                available.append({
                    "index": i,
                    "name": _format_camera_name(i, system_names),
                    "resolution": f"{width}x{height}"
                })
                cap.release()
        return available


camera_manager = CameraManager()
