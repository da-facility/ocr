from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from tkinter import (
    BOTH,
    BOTTOM,
    END,
    LEFT,
    RIGHT,
    TOP,
    X,
    Y,
    BooleanVar,
    Canvas,
    Checkbutton,
    Entry,
    Frame,
    Label,
    LabelFrame,
    Listbox,
    Menu,
    StringVar,
    Tk,
    filedialog,
    messagebox,
    ttk,
    simpledialog,
)
from typing import Literal

import cv2
import numpy as np
from PIL import Image, ImageTk

try:
    import pytesseract
except Exception:  # pragma: no cover
    pytesseract = None


Engine = Literal["lexicon", "digits", "tesseract"]
OutputKind = Literal["folder", "file", "url"]


APP_DIR = Path.home() / ".ocr-console-python"
APP_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = APP_DIR / "state.json"


ZONE_COLORS = ["#d44d1c", "#1859c4", "#107362", "#9b3f16", "#735b08", "#8d2459"]
DIGIT_SEGMENTS = {
    "0": (1, 1, 1, 0, 1, 1, 1),
    "1": (0, 0, 1, 0, 0, 1, 0),
    "2": (1, 0, 1, 1, 1, 0, 1),
    "3": (1, 0, 1, 1, 0, 1, 1),
    "4": (0, 1, 1, 1, 0, 1, 0),
    "5": (1, 1, 0, 1, 0, 1, 1),
    "6": (1, 1, 0, 1, 1, 1, 1),
    "7": (1, 0, 1, 0, 0, 1, 0),
    "8": (1, 1, 1, 1, 1, 1, 1),
    "9": (1, 1, 1, 1, 0, 1, 1),
}


@dataclass
class Zone:
    id: str
    label: str
    x: int
    y: int
    width: int
    height: int
    color: str
    engine: Engine = "digits"


@dataclass
class OutputTarget:
    id: str
    kind: OutputKind
    value: str
    enabled: bool = True


@dataclass
class AppState:
    camera_index: int = 0
    threshold: int = 172
    invert: bool = False
    processing: bool = True
    erode: int = 0
    dilate: int = 0
    zones: list[Zone] = field(default_factory=list)
    outputs: list[OutputTarget] = field(default_factory=list)


def load_state() -> AppState:
    if not STATE_FILE.exists():
        return AppState()

    try:
        data = json.loads(STATE_FILE.read_text())
        return AppState(
            camera_index=int(data.get("camera_index", 0)),
            threshold=int(data.get("threshold", 172)),
            invert=bool(data.get("invert", False)),
            processing=bool(data.get("processing", True)),
            erode=int(data.get("erode", 0)),
            dilate=int(data.get("dilate", 0)),
            zones=[Zone(**zone) for zone in data.get("zones", [])],
            outputs=[OutputTarget(**target) for target in data.get("outputs", [])],
        )
    except Exception:
        return AppState()


def save_state(state: AppState) -> None:
    payload = asdict(state)
    STATE_FILE.write_text(json.dumps(payload, indent=2))


def sanitize_file_name(value: str) -> str:
    cleaned = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in value.strip())
    cleaned = "-".join(cleaned.split()).rstrip(".")
    return cleaned[:80] or "zone"


def threshold_image(frame: np.ndarray, threshold: int, invert: bool) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mode = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
    _, binary = cv2.threshold(gray, threshold, 255, mode)
    return binary


def apply_morphology(binary: np.ndarray, erode: int, dilate: int) -> np.ndarray:
    kernel = np.ones((3, 3), np.uint8)
    out = binary
    if erode > 0:
        out = cv2.erode(out, kernel, iterations=erode)
    if dilate > 0:
        out = cv2.dilate(out, kernel, iterations=dilate)
    return out


def component_boxes(binary: np.ndarray, min_area: int) -> list[tuple[int, int, int, int, int]]:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    boxes: list[tuple[int, int, int, int, int]] = []
    for idx in range(1, count):
        x, y, w, h, area = [int(v) for v in stats[idx]]
        if area >= min_area and w >= 2 and h >= 4:
            boxes.append((x, y, w, h, area))
    return sorted(boxes, key=lambda box: box[0])


def crop(binary: np.ndarray, box: tuple[int, int, int, int, int]) -> np.ndarray:
    x, y, w, h, _ = box
    return binary[y : y + h, x : x + w]


def ratio(img: np.ndarray, left: float, top: float, right: float, bottom: float) -> float:
    h, w = img.shape[:2]
    x0 = max(0, min(w - 1, int(left * w)))
    y0 = max(0, min(h - 1, int(top * h)))
    x1 = max(x0 + 1, min(w, int(np.ceil(right * w))))
    y1 = max(y0 + 1, min(h, int(np.ceil(bottom * h))))
    region = img[y0:y1, x0:x1]
    return float(np.count_nonzero(region)) / float(region.size or 1)


def classify_digit(img: np.ndarray) -> str:
    h, w = img.shape[:2]
    area = int(np.count_nonzero(img))
    aspect = w / max(1, h)
    fill = area / max(1, w * h)

    if aspect <= 0.42 and fill <= 0.5:
        upper = ratio(img, 0.1, 0.05, 0.9, 0.4)
        middle = ratio(img, 0.1, 0.4, 0.9, 0.6)
        lower = ratio(img, 0.1, 0.6, 0.9, 0.95)
        if upper > 0.12 and lower > 0.12 and middle < max(upper, lower) * 0.65:
            return ":"
        return "1"

    segments = [
        ratio(img, 0.2, 0.0, 0.8, 0.2),
        ratio(img, 0.0, 0.12, 0.35, 0.48),
        ratio(img, 0.65, 0.12, 1.0, 0.48),
        ratio(img, 0.2, 0.4, 0.8, 0.6),
        ratio(img, 0.0, 0.52, 0.35, 0.88),
        ratio(img, 0.65, 0.52, 1.0, 0.88),
        ratio(img, 0.2, 0.8, 0.8, 1.0),
    ]
    active = tuple(1 if value >= 0.16 else 0 for value in segments)
    best = "?"
    best_score = 999.0
    for digit, expected in DIGIT_SEGMENTS.items():
        score = 0.0
        for index, value in enumerate(expected):
            score += 0 if value == active[index] else 1
            score += max(0.0, 0.28 - segments[index]) if value else max(0.0, segments[index] - 0.18)
        if score < best_score:
            best = digit
            best_score = score
    return best if best_score <= 3.2 else "?"


def recognize_digits(binary: np.ndarray) -> tuple[str, list[tuple[int, int, int, int, str]]]:
    min_area = max(8, int(binary.shape[0] * binary.shape[1] * 0.0004))
    min_height = max(6, int(binary.shape[0] * 0.08))
    detections = []
    for box in component_boxes(binary, min_area):
        x, y, w, h, area = box
        if h < min_height:
            continue
        label = classify_digit(crop(binary, box))
        detections.append((x, y, w, h, label))
    return "".join(item[4] for item in detections), detections


def recognize_tesseract(frame: np.ndarray) -> str:
    if pytesseract is None:
        return ""
    try:
        return pytesseract.image_to_string(frame, config="--psm 7").strip()
    except Exception:
        return ""


class OcrApp:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("OCR Console")
        self.root.geometry("1280x860")
        self.root.configure(bg="#111")
        self.state = load_state()
        self.cap: cv2.VideoCapture | None = None
        self.raw_frame: np.ndarray | None = None
        self.processed_frame: np.ndarray | None = None
        self.results: dict[str, str] = {}
        self.detections: dict[str, list[tuple[int, int, int, int, str]]] = {}
        self.photo: ImageTk.PhotoImage | None = None
        self.view_scale = 1.0
        self.view_offset = (0, 0)
        self.draw_start: tuple[int, int] | None = None
        self.selected_zone_id: str | None = None
        self.last_output_at = 0.0

        self.camera_var = StringVar(value=str(self.state.camera_index))
        self.status_var = StringVar(value="camera closed")
        self.processing_var = BooleanVar(value=self.state.processing)
        self.invert_var = BooleanVar(value=self.state.invert)
        self.threshold_var = StringVar(value=str(self.state.threshold))
        self.erode_var = StringVar(value=str(self.state.erode))
        self.dilate_var = StringVar(value=str(self.state.dilate))
        self.zone_label_var = StringVar()
        self.zone_engine_var = StringVar(value="digits")
        self.output_status_var = StringVar(value="No output destinations.")

        self._build_ui()
        self._refresh_zone_list()
        self._refresh_output_list()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(30, self.tick)

    def _build_ui(self) -> None:
        header = Frame(self.root, bg="#111")
        header.pack(side=TOP, fill=X)
        Label(header, text="OCR Console", fg="#fff", bg="#111", font=("Arial", 16, "bold")).pack(side=LEFT, padx=10, pady=8)
        Label(header, textvariable=self.status_var, fg="#ddd", bg="#111").pack(side=LEFT, padx=12)

        body = Frame(self.root, bg="#d8d8d8")
        body.pack(fill=BOTH, expand=True)

        self.canvas = Canvas(body, bg="#000", highlightthickness=0)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_down)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_up)

        sidebar = Frame(body, width=360, bg="#efefef")
        sidebar.pack(side=RIGHT, fill=Y)
        sidebar.pack_propagate(False)

        capture = LabelFrame(sidebar, text="capture", bg="#efefef")
        capture.pack(fill=X, padx=8, pady=6)
        Entry(capture, textvariable=self.camera_var, width=8).pack(side=LEFT, padx=6, pady=6)
        ttk.Button(capture, text="open", command=self.open_camera).pack(side=LEFT, padx=3)
        ttk.Button(capture, text="close", command=self.close_camera).pack(side=LEFT, padx=3)

        processing = LabelFrame(sidebar, text="colors / morphology", bg="#efefef")
        processing.pack(fill=X, padx=8, pady=6)
        Checkbutton(processing, text="processing", variable=self.processing_var, bg="#efefef", command=self.persist_controls).grid(row=0, column=0, sticky="w", padx=6)
        Checkbutton(processing, text="invert", variable=self.invert_var, bg="#efefef", command=self.persist_controls).grid(row=0, column=1, sticky="w")
        Label(processing, text="threshold", bg="#efefef").grid(row=1, column=0, sticky="w", padx=6)
        Entry(processing, textvariable=self.threshold_var, width=8).grid(row=1, column=1, sticky="w")
        Label(processing, text="erode", bg="#efefef").grid(row=2, column=0, sticky="w", padx=6)
        Entry(processing, textvariable=self.erode_var, width=8).grid(row=2, column=1, sticky="w")
        Label(processing, text="dilate", bg="#efefef").grid(row=3, column=0, sticky="w", padx=6)
        Entry(processing, textvariable=self.dilate_var, width=8).grid(row=3, column=1, sticky="w")

        zones = LabelFrame(sidebar, text="zones", bg="#efefef")
        zones.pack(fill=BOTH, expand=True, padx=8, pady=6)
        Label(zones, text="drag on viewer to create zone", bg="#efefef").pack(anchor="w", padx=6)
        self.zone_list = Listbox(zones, height=7)
        self.zone_list.pack(fill=X, padx=6, pady=4)
        self.zone_list.bind("<<ListboxSelect>>", self.select_zone_from_list)
        Label(zones, text="name", bg="#efefef").pack(anchor="w", padx=6)
        Entry(zones, textvariable=self.zone_label_var).pack(fill=X, padx=6)
        Label(zones, text="engine", bg="#efefef").pack(anchor="w", padx=6)
        ttk.Combobox(zones, textvariable=self.zone_engine_var, values=["lexicon", "digits", "tesseract"], state="readonly").pack(fill=X, padx=6)
        row = Frame(zones, bg="#efefef")
        row.pack(fill=X, padx=6, pady=5)
        ttk.Button(row, text="apply", command=self.apply_zone_edits).pack(side=LEFT)
        ttk.Button(row, text="delete", command=self.delete_selected_zone).pack(side=LEFT, padx=4)

        outputs = LabelFrame(sidebar, text="output", bg="#efefef")
        outputs.pack(fill=BOTH, padx=8, pady=6)
        self.output_list = Listbox(outputs, height=5)
        self.output_list.pack(fill=X, padx=6, pady=4)
        row = Frame(outputs, bg="#efefef")
        row.pack(fill=X, padx=6, pady=4)
        ttk.Button(row, text="+ folder", command=self.add_output_folder).pack(side=LEFT)
        ttk.Button(row, text="+ file", command=self.add_output_file).pack(side=LEFT, padx=4)
        ttk.Button(row, text="+ url", command=self.add_output_url).pack(side=LEFT)
        row2 = Frame(outputs, bg="#efefef")
        row2.pack(fill=X, padx=6, pady=4)
        ttk.Button(row2, text="pause/resume", command=self.toggle_selected_output).pack(side=LEFT)
        ttk.Button(row2, text="delete", command=self.delete_selected_output).pack(side=LEFT, padx=4)
        Label(outputs, textvariable=self.output_status_var, bg="#efefef", wraplength=320, justify=LEFT).pack(fill=X, padx=6, pady=4)

        footer = Frame(self.root, bg="#f6f6f6", height=72)
        footer.pack(side=BOTTOM, fill=X)
        self.results_label = Label(footer, text="no zones", bg="#f6f6f6", anchor="w", justify=LEFT)
        self.results_label.pack(fill=BOTH, padx=10, pady=8)

    def persist_controls(self) -> None:
        self.state.camera_index = self.camera_index()
        self.state.processing = self.processing_var.get()
        self.state.invert = self.invert_var.get()
        self.state.threshold = self.int_var(self.threshold_var, 172)
        self.state.erode = self.int_var(self.erode_var, 0)
        self.state.dilate = self.int_var(self.dilate_var, 0)
        save_state(self.state)

    def int_var(self, var: StringVar, fallback: int) -> int:
        try:
            return int(var.get())
        except ValueError:
            return fallback

    def camera_index(self) -> int:
        return self.int_var(self.camera_var, 0)

    def open_camera(self) -> None:
        self.close_camera()
        self.cap = cv2.VideoCapture(self.camera_index())
        if not self.cap.isOpened():
            self.cap = None
            self.status_var.set("camera unavailable")
            return
        self.persist_controls()
        self.status_var.set(f"camera {self.camera_index()} open")

    def close_camera(self) -> None:
        if self.cap is not None:
            self.cap.release()
        self.cap = None
        self.status_var.set("camera closed")

    def tick(self) -> None:
        if self.cap is not None:
            ok, frame = self.cap.read()
            if ok:
                self.raw_frame = frame
                self.processed_frame = self.process(frame)
                self.run_recognition()
                if time.time() - self.last_output_at > 0.5:
                    self.write_outputs()
                    self.last_output_at = time.time()
                self.paint(frame)
            else:
                self.status_var.set("camera disconnected")
                self.close_camera()
        self.root.after(45, self.tick)

    def process(self, frame: np.ndarray) -> np.ndarray:
        self.persist_controls()
        if not self.state.processing:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        binary = threshold_image(frame, self.state.threshold, self.state.invert)
        return apply_morphology(binary, self.state.erode, self.state.dilate)

    def frame_to_view(self, x: int, y: int) -> tuple[int, int]:
        ox, oy = self.view_offset
        return int(x * self.view_scale + ox), int(y * self.view_scale + oy)

    def view_to_frame(self, x: int, y: int) -> tuple[int, int]:
        ox, oy = self.view_offset
        return int((x - ox) / self.view_scale), int((y - oy) / self.view_scale)

    def paint(self, frame: np.ndarray) -> None:
        canvas_w = max(1, self.canvas.winfo_width())
        canvas_h = max(1, self.canvas.winfo_height())
        h, w = frame.shape[:2]
        scale = min(canvas_w / w, canvas_h / h)
        self.view_scale = scale
        self.view_offset = (int((canvas_w - w * scale) / 2), int((canvas_h - h * scale) / 2))

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb).resize((int(w * scale), int(h * scale)))
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(*self.view_offset, image=self.photo, anchor="nw")

        for zone in self.state.zones:
            self.draw_zone(zone)
        if self.draw_start and self.raw_frame is not None:
            x0, y0 = self.frame_to_view(*self.draw_start)
            x1, y1 = self.canvas.winfo_pointerx() - self.canvas.winfo_rootx(), self.canvas.winfo_pointery() - self.canvas.winfo_rooty()
            self.canvas.create_rectangle(x0, y0, x1, y1, outline="#fff", dash=(6, 4), width=2)

    def draw_zone(self, zone: Zone) -> None:
        x0, y0 = self.frame_to_view(zone.x, zone.y)
        x1, y1 = self.frame_to_view(zone.x + zone.width, zone.y + zone.height)
        border = 4
        self.canvas.create_rectangle(x0 - border, y0 - border, x1 + border, y1 + border, outline=zone.color, width=border)
        label = f"{zone.label} · {zone.engine}"
        tab_w = min(max(70, len(label) * 8 + 18), max(70, x1 - x0))
        self.canvas.create_rectangle(x0 - border, y0 - 28, x0 - border + tab_w, y0, fill=zone.color, outline=zone.color)
        self.canvas.create_text(x0 + 8, y0 - 14, text=label, anchor="w", fill="#000", font=("Arial", 13, "bold"), width=tab_w - 14)
        if zone.engine == "digits":
            for dx, dy, dw, dh, text in self.detections.get(zone.id, []):
                ax0, ay0 = self.frame_to_view(zone.x + dx, zone.y + dy)
                ax1, ay1 = self.frame_to_view(zone.x + dx + dw, zone.y + dy + dh)
                self.canvas.create_rectangle(ax0, ay0, ax1, ay1, outline="#00f0c8", dash=(3, 2), width=2)
                self.canvas.create_text(ax0 + 3, ay0 - 8, text=text, anchor="w", fill="#00f0c8", font=("Arial", 11, "bold"))

    def zone_at(self, x: int, y: int) -> Zone | None:
        for zone in reversed(self.state.zones):
            if zone.x <= x <= zone.x + zone.width and zone.y <= y <= zone.y + zone.height:
                return zone
        return None

    def on_canvas_down(self, event) -> None:
        x, y = self.view_to_frame(event.x, event.y)
        hit = self.zone_at(x, y)
        if hit:
            self.selected_zone_id = hit.id
            self._sync_zone_editor(hit)
            self._refresh_zone_list()
            return
        self.draw_start = (x, y)

    def on_canvas_drag(self, _event) -> None:
        pass

    def on_canvas_up(self, event) -> None:
        if not self.draw_start:
            return
        x0, y0 = self.draw_start
        x1, y1 = self.view_to_frame(event.x, event.y)
        self.draw_start = None
        if abs(x1 - x0) < 10 or abs(y1 - y0) < 10:
            return
        index = len(self.state.zones)
        zone = Zone(
            id=f"zone-{int(time.time() * 1000)}",
            label=f"ocr-{index + 1}",
            x=min(x0, x1),
            y=min(y0, y1),
            width=abs(x1 - x0),
            height=abs(y1 - y0),
            color=ZONE_COLORS[index % len(ZONE_COLORS)],
            engine="digits",
        )
        self.state.zones.append(zone)
        self.selected_zone_id = zone.id
        self._sync_zone_editor(zone)
        save_state(self.state)
        self._refresh_zone_list()

    def selected_zone(self) -> Zone | None:
        return next((zone for zone in self.state.zones if zone.id == self.selected_zone_id), None)

    def select_zone_from_list(self, _event) -> None:
        selection = self.zone_list.curselection()
        if not selection:
            return
        zone = self.state.zones[selection[0]]
        self.selected_zone_id = zone.id
        self._sync_zone_editor(zone)

    def _sync_zone_editor(self, zone: Zone) -> None:
        self.zone_label_var.set(zone.label)
        self.zone_engine_var.set(zone.engine)

    def apply_zone_edits(self) -> None:
        zone = self.selected_zone()
        if not zone:
            return
        zone.label = self.zone_label_var.get().strip() or zone.label
        zone.engine = self.zone_engine_var.get()  # type: ignore[assignment]
        save_state(self.state)
        self._refresh_zone_list()

    def delete_selected_zone(self) -> None:
        zone = self.selected_zone()
        if not zone:
            return
        self.state.zones = [candidate for candidate in self.state.zones if candidate.id != zone.id]
        self.selected_zone_id = None
        save_state(self.state)
        self._refresh_zone_list()

    def _refresh_zone_list(self) -> None:
        self.zone_list.delete(0, END)
        for zone in self.state.zones:
            prefix = "• " if zone.id == self.selected_zone_id else "  "
            self.zone_list.insert(END, f"{prefix}{zone.label} · {zone.engine}")

    def run_recognition(self) -> None:
        if self.raw_frame is None or self.processed_frame is None:
            return
        results: dict[str, str] = {}
        detections: dict[str, list[tuple[int, int, int, int, str]]] = {}
        for zone in self.state.zones:
            crop_raw = self.raw_frame[zone.y : zone.y + zone.height, zone.x : zone.x + zone.width]
            crop_processed = self.processed_frame[zone.y : zone.y + zone.height, zone.x : zone.x + zone.width]
            if crop_raw.size == 0 or crop_processed.size == 0:
                results[zone.id] = ""
                continue
            if zone.engine == "tesseract":
                results[zone.id] = recognize_tesseract(crop_raw)
            elif zone.engine == "digits":
                binary = crop_processed if len(crop_processed.shape) == 2 else threshold_image(crop_raw, self.state.threshold, self.state.invert)
                text, found = recognize_digits(binary)
                results[zone.id] = text
                detections[zone.id] = found
            else:
                text, _ = recognize_digits(crop_processed if len(crop_processed.shape) == 2 else threshold_image(crop_raw, self.state.threshold, self.state.invert))
                results[zone.id] = text
        self.results = results
        self.detections = detections
        self.results_label.configure(text="   ".join(f"{z.label}: {results.get(z.id, '') or '—'}" for z in self.state.zones) or "no zones")

    def add_output_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose OCR output folder")
        if not folder:
            return
        target = OutputTarget(id=f"out-{time.time_ns()}", kind="folder", value=folder)
        self.state.outputs.append(target)
        save_state(self.state)
        self._refresh_output_list()

    def add_output_file(self) -> None:
        file_path = filedialog.asksaveasfilename(title="Choose OCR output file", defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if not file_path:
            return
        target = OutputTarget(id=f"out-{time.time_ns()}", kind="file", value=file_path)
        self.state.outputs.append(target)
        save_state(self.state)
        self._refresh_output_list()

    def add_output_url(self) -> None:
        url = simpledialog.askstring("Add URL output", "Webhook URL:")
        if not url:
            return
        target = OutputTarget(id=f"out-{time.time_ns()}", kind="url", value=url, enabled=False)
        self.state.outputs.append(target)
        save_state(self.state)
        self._refresh_output_list()

    def selected_output(self) -> OutputTarget | None:
        selection = self.output_list.curselection()
        if not selection:
            return None
        return self.state.outputs[selection[0]]

    def toggle_selected_output(self) -> None:
        target = self.selected_output()
        if not target:
            return
        target.enabled = not target.enabled
        save_state(self.state)
        self._refresh_output_list()

    def delete_selected_output(self) -> None:
        target = self.selected_output()
        if not target:
            return
        self.state.outputs = [candidate for candidate in self.state.outputs if candidate.id != target.id]
        save_state(self.state)
        self._refresh_output_list()

    def _refresh_output_list(self) -> None:
        self.output_list.delete(0, END)
        for target in self.state.outputs:
            state = "live" if target.enabled else "paused"
            self.output_list.insert(END, f"{state} · {target.kind} · {target.value}")

    def write_outputs(self) -> None:
        if not self.state.outputs:
            return
        ordered = [(zone, self.results.get(zone.id, "")) for zone in self.state.zones]
        messages = []
        for target in self.state.outputs:
            if not target.enabled:
                continue
            try:
                if target.kind == "folder":
                    folder = Path(target.value)
                    folder.mkdir(parents=True, exist_ok=True)
                    for zone, text in ordered:
                        (folder / f"{sanitize_file_name(zone.label or zone.id)}.txt").write_text(text)
                    (folder / "ocr-live.txt").write_text("\n".join(f"{zone.label}: {text}" for zone, text in ordered))
                    messages.append(f"folder {folder.name}")
                elif target.kind == "file":
                    Path(target.value).write_text("\n".join(f"{zone.label}: {text}" for zone, text in ordered))
                    messages.append(f"file {Path(target.value).name}")
                elif target.kind == "url":
                    payload = json.dumps({"timestamp": time.time(), "zones": [{"id": z.id, "label": z.label, "text": t} for z, t in ordered]}).encode()
                    request = urllib.request.Request(target.value, data=payload, headers={"content-type": "application/json"}, method="POST")
                    urllib.request.urlopen(request, timeout=2).read()
                    messages.append("url sent")
            except Exception as exc:
                messages.append(str(exc))
        self.output_status_var.set(" · ".join(messages) if messages else "No live outputs.")

    def close(self) -> None:
        self.persist_controls()
        self.close_camera()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    OcrApp().run()
