from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid
import json
import os
import sys


def get_data_path() -> str:
    """Get directory for user data files (sessions, glyphs, etc.)."""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe - use exe's directory
        return os.path.dirname(sys.executable)
    # Running as script - use current working directory
    return os.getcwd()


@dataclass
class ColorFilter:
    """A color filter with BGR color and tolerance values."""
    id: str
    bgr: list[int]  # [B, G, R]
    tolerance: list[int] = field(default_factory=lambda: [30, 30, 30])  # tolerance for each channel

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "bgr": self.bgr,
            "tolerance": self.tolerance
        }


@dataclass
class Glyph:
    """A glyph template for custom OCR matching."""
    id: str
    char: str  # The character this glyph represents (e.g., "1", "5", ":")
    template: list[list[int]]  # Normalized binary template (2D array of 0/255)
    width: int  # Original width before normalization
    height: int  # Original height before normalization
    ignored: bool = False  # If True, this glyph is ignored during recognition

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "char": self.char,
            "template": self.template,
            "width": self.width,
            "height": self.height,
            "ignored": self.ignored
        }


@dataclass
class OcrRegion:
    """A rectangular region of interest for OCR."""
    id: str
    x: int
    y: int
    width: int
    height: int
    label: str = ""
    ocr_backend: str = "glyphs"  # Only "glyphs" supported
    region_type: str = "generic"  # "generic", "time", or "score"
    score_subtype: Optional[str] = None  # For score type: None or "singles"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "label": self.label,
            "ocr_backend": self.ocr_backend,
            "region_type": self.region_type,
            "score_subtype": self.score_subtype
        }


@dataclass
class Session:
    id: str
    camera_index: int
    camera_name: str = ""
    camera_device_name: str = ""
    camera_vid: Optional[int] = None
    camera_pid: Optional[int] = None
    perspective_points: Optional[list[tuple[int, int]]] = None
    perspective_output_size: tuple[int, int] = (800, 600)
    color_filters: list[ColorFilter] = field(default_factory=list)
    erosion_kernel: int = 0
    dilation_kernel: int = 0
    ocr_regions: list[OcrRegion] = field(default_factory=list)
    glyphs: list[Glyph] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "camera_index": self.camera_index,
            "camera_name": self.camera_name,
            "camera_device_name": self.camera_device_name,
            "camera_vid": self.camera_vid,
            "camera_pid": self.camera_pid,
            "perspective_points": self.perspective_points,
            "perspective_output_size": list(self.perspective_output_size),
            "color_filters": [cf.to_dict() for cf in self.color_filters],
            "erosion_kernel": self.erosion_kernel,
            "dilation_kernel": self.dilation_kernel,
            "ocr_regions": [r.to_dict() for r in self.ocr_regions],
            "glyphs": [g.to_dict() for g in self.glyphs],
            "created_at": self.created_at.isoformat()
        }
    
    def get_region_by_name(self, name: str) -> Optional[OcrRegion]:
        for region in self.ocr_regions:
            if region.label == name:
                return region
        return None
    
    def is_region_name_unique(self, name: str, exclude_id: Optional[str] = None) -> bool:
        for region in self.ocr_regions:
            if region.label == name and region.id != exclude_id:
                return False
        return True


SESSIONS_FILE = os.path.join(get_data_path(), "sessions.json")


class SessionManager:
    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self.load_sessions()

    def save_sessions(self):
        """Save all sessions to JSON file."""
        try:
            data = {sid: s.to_dict() for sid, s in self.sessions.items()}
            with open(SESSIONS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Failed to save sessions: {e}")

    def load_sessions(self):
        """Load sessions from JSON file."""
        if not os.path.exists(SESSIONS_FILE):
            print(f"[Sessions] No session file at: {SESSIONS_FILE}")
            return

        print(f"[Sessions] Loading from: {SESSIONS_FILE}")
        
        try:
            with open(SESSIONS_FILE, 'r') as f:
                data = json.load(f)
            
            for sid, sdata in data.items():
                color_filters = [
                    ColorFilter(id=cf['id'], bgr=cf['bgr'], tolerance=cf['tolerance'])
                    for cf in sdata.get('color_filters', [])
                ]
                ocr_regions = [
                    OcrRegion(id=r['id'], x=r['x'], y=r['y'], width=r['width'], height=r['height'], 
                              label=r['label'], ocr_backend='glyphs',
                              region_type=r.get('region_type', 'generic'),
                              score_subtype=r.get('score_subtype'))
                    for r in sdata.get('ocr_regions', [])
                ]
                glyphs = [
                    Glyph(id=g['id'], char=g['char'], template=g['template'], 
                          width=g['width'], height=g['height'],
                          ignored=g.get('ignored', False))
                    for g in sdata.get('glyphs', [])
                ]
                
                perspective_points = None
                if sdata.get('perspective_points'):
                    perspective_points = [tuple(p) for p in sdata['perspective_points']]
                
                session = Session(
                    id=sdata['id'],
                    camera_index=sdata['camera_index'],
                    camera_name=sdata.get('camera_name', ''),
                    camera_device_name=sdata.get('camera_device_name', sdata.get('camera_name', '')),
                    camera_vid=sdata.get('camera_vid'),
                    camera_pid=sdata.get('camera_pid'),
                    perspective_points=perspective_points,
                    perspective_output_size=tuple(sdata.get('perspective_output_size', [800, 600])),
                    color_filters=color_filters,
                    erosion_kernel=sdata.get('erosion_kernel', 0),
                    dilation_kernel=sdata.get('dilation_kernel', 0),
                    ocr_regions=ocr_regions,
                    glyphs=glyphs,
                    created_at=datetime.fromisoformat(sdata['created_at']) if 'created_at' in sdata else datetime.now()
                )
                self.sessions[sid] = session
            
            print(f"[Sessions] Loaded {len(self.sessions)} sessions")
        except Exception as e:
            print(f"Failed to load sessions: {e}")

    def create_session(
        self,
        camera_index: int,
        camera_name: str = "",
        camera_device_name: str = "",
        camera_vid: Optional[int] = None,
        camera_pid: Optional[int] = None,
    ) -> Session:
        session_id = str(uuid.uuid4())[:8]
        default_name = f"Camera {camera_index + 1:02d}"
        session = Session(
            id=session_id,
            camera_index=camera_index,
            camera_name=camera_name or default_name,
            camera_device_name=camera_device_name or camera_name or default_name,
            camera_vid=camera_vid,
            camera_pid=camera_pid,
        )
        self.sessions[session_id] = session
        self.save_sessions()
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        return self.sessions.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        if session_id in self.sessions:
            del self.sessions[session_id]
            self.save_sessions()
            return True
        return False

    def list_sessions(self) -> list[Session]:
        return list(self.sessions.values())

    def update_perspective(self, session_id: str, points: Optional[list[tuple[int, int]]], 
                           output_size: Optional[tuple[int, int]] = None) -> bool:
        session = self.get_session(session_id)
        if session:
            session.perspective_points = points
            if output_size:
                session.perspective_output_size = output_size
            self.save_sessions()
            return True
        return False

    def add_color_filter(self, session_id: str, bgr: list[int], tolerance: list[int]) -> Optional[ColorFilter]:
        session = self.get_session(session_id)
        if session:
            filter_id = str(uuid.uuid4())[:8]
            cf = ColorFilter(id=filter_id, bgr=bgr, tolerance=tolerance)
            session.color_filters.append(cf)
            self.save_sessions()
            return cf
        return None

    def update_color_filter(self, session_id: str, filter_id: str, 
                            tolerance: Optional[list[int]] = None) -> bool:
        session = self.get_session(session_id)
        if session:
            for cf in session.color_filters:
                if cf.id == filter_id:
                    if tolerance is not None:
                        cf.tolerance = tolerance
                    self.save_sessions()
                    return True
        return False

    def delete_color_filter(self, session_id: str, filter_id: str) -> bool:
        session = self.get_session(session_id)
        if session:
            session.color_filters = [cf for cf in session.color_filters if cf.id != filter_id]
            self.save_sessions()
            return True
        return False

    def clear_color_filters(self, session_id: str) -> bool:
        session = self.get_session(session_id)
        if session:
            session.color_filters = []
            self.save_sessions()
            return True
        return False

    def update_morphology(self, session_id: str, erosion_kernel: Optional[int] = None,
                          dilation_kernel: Optional[int] = None) -> bool:
        session = self.get_session(session_id)
        if session:
            if erosion_kernel is not None:
                session.erosion_kernel = erosion_kernel
            if dilation_kernel is not None:
                session.dilation_kernel = dilation_kernel
            self.save_sessions()
            return True
        return False

    def add_ocr_region(self, session_id: str, x: int, y: int, width: int, height: int, 
                       label: str = "") -> Optional[OcrRegion]:
        session = self.get_session(session_id)
        if session:
            region_id = str(uuid.uuid4())[:8]
            
            if not label:
                counter = len(session.ocr_regions) + 1
                label = f"region_{counter}"
                while not session.is_region_name_unique(label):
                    counter += 1
                    label = f"region_{counter}"
            elif not session.is_region_name_unique(label):
                return None
            
            region = OcrRegion(id=region_id, x=x, y=y, width=width, height=height, label=label)
            session.ocr_regions.append(region)
            self.save_sessions()
            return region
        return None

    def update_ocr_region(self, session_id: str, region_id: str, 
                          x: Optional[int] = None, y: Optional[int] = None,
                          width: Optional[int] = None, height: Optional[int] = None,
                          label: Optional[str] = None, ocr_backend: Optional[str] = None,
                          region_type: Optional[str] = None, score_subtype: Optional[str] = None) -> bool:
        session = self.get_session(session_id)
        if session:
            for region in session.ocr_regions:
                if region.id == region_id:
                    if label is not None and label != region.label:
                        if not session.is_region_name_unique(label, exclude_id=region_id):
                            return False
                        region.label = label
                    if x is not None:
                        region.x = x
                    if y is not None:
                        region.y = y
                    if width is not None:
                        region.width = width
                    if height is not None:
                        region.height = height
                    if ocr_backend is not None:
                        region.ocr_backend = ocr_backend
                    if region_type is not None:
                        region.region_type = region_type
                    if score_subtype is not None:
                        region.score_subtype = score_subtype if score_subtype else None
                    self.save_sessions()
                    return True
        return False

    def delete_ocr_region(self, session_id: str, region_id: str) -> bool:
        session = self.get_session(session_id)
        if session:
            session.ocr_regions = [r for r in session.ocr_regions if r.id != region_id]
            self.save_sessions()
            return True
        return False

    def clear_ocr_regions(self, session_id: str) -> bool:
        session = self.get_session(session_id)
        if session:
            session.ocr_regions = []
            self.save_sessions()
            return True
        return False

    def add_glyph(self, session_id: str, char: str, template: list[list[int]], 
                  width: int, height: int, ignored: bool = False) -> Optional[Glyph]:
        session = self.get_session(session_id)
        if session:
            glyph_id = str(uuid.uuid4())[:8]
            glyph = Glyph(id=glyph_id, char=char, template=template, width=width, height=height, ignored=ignored)
            session.glyphs.append(glyph)
            self.save_sessions()
            return glyph
        return None

    def update_glyph(self, session_id: str, glyph_id: str, char: Optional[str] = None,
                     ignored: Optional[bool] = None) -> bool:
        session = self.get_session(session_id)
        if session:
            for glyph in session.glyphs:
                if glyph.id == glyph_id:
                    if char is not None:
                        glyph.char = char
                    if ignored is not None:
                        glyph.ignored = ignored
                    self.save_sessions()
                    return True
        return False

    def delete_glyph(self, session_id: str, glyph_id: str) -> bool:
        session = self.get_session(session_id)
        if session:
            session.glyphs = [g for g in session.glyphs if g.id != glyph_id]
            self.save_sessions()
            return True
        return False

    def clear_glyphs(self, session_id: str) -> bool:
        session = self.get_session(session_id)
        if session:
            session.glyphs = []
            self.save_sessions()
            return True
        return False

    def get_glyphs(self, session_id: str) -> list[Glyph]:
        session = self.get_session(session_id)
        if session:
            return session.glyphs
        return []


session_manager = SessionManager()
