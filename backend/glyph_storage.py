"""
Global glyph storage for managing reusable glyph sets across sessions.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid
import json
import os

from sessions import Glyph, session_manager, get_data_path


GLYPHS_FILE = os.path.join(get_data_path(), "glyph_sets.json")


@dataclass
class GlyphSet:
    """A named collection of glyph templates."""
    id: str
    name: str
    glyphs: list[Glyph]
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "glyphs": [g.to_dict() for g in self.glyphs],
            "created_at": self.created_at.isoformat()
        }


class GlyphStorageManager:
    """Manages global glyph sets that can be exported/imported to sessions."""
    
    def __init__(self):
        self.glyph_sets: dict[str, GlyphSet] = {}
        self.load_glyph_sets()
    
    def save_glyph_sets(self):
        """Save all glyph sets to JSON file."""
        try:
            data = {set_id: gs.to_dict() for set_id, gs in self.glyph_sets.items()}
            with open(GLYPHS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Failed to save glyph sets: {e}")
    
    def load_glyph_sets(self):
        """Load glyph sets from JSON file."""
        if not os.path.exists(GLYPHS_FILE):
            print(f"[GlyphSets] No glyph sets file at: {GLYPHS_FILE}")
            return

        print(f"[GlyphSets] Loading from: {GLYPHS_FILE}")
        
        try:
            with open(GLYPHS_FILE, 'r') as f:
                data = json.load(f)
            
            for set_id, sdata in data.items():
                glyphs = [
                    Glyph(
                        id=g['id'],
                        char=g['char'],
                        template=g['template'],
                        width=g['width'],
                        height=g['height'],
                        ignored=g.get('ignored', False)
                    )
                    for g in sdata.get('glyphs', [])
                ]
                
                glyph_set = GlyphSet(
                    id=sdata['id'],
                    name=sdata['name'],
                    glyphs=glyphs,
                    created_at=datetime.fromisoformat(sdata['created_at']) if 'created_at' in sdata else datetime.now()
                )
                self.glyph_sets[set_id] = glyph_set
            
            print(f"[GlyphSets] Loaded {len(self.glyph_sets)} glyph sets")
        except Exception as e:
            print(f"Failed to load glyph sets: {e}")
    
    def list_glyph_sets(self) -> list[dict]:
        """List all glyph sets (without full glyph data for efficiency)."""
        result = []
        for gs in self.glyph_sets.values():
            result.append({
                "id": gs.id,
                "name": gs.name,
                "glyph_count": len(gs.glyphs),
                "created_at": gs.created_at.isoformat()
            })
        return result
    
    def get_glyph_set(self, set_id: str) -> Optional[GlyphSet]:
        """Get a specific glyph set by ID."""
        return self.glyph_sets.get(set_id)
    
    def create_glyph_set(self, name: str, glyphs: list[Glyph]) -> GlyphSet:
        """Create a new glyph set from provided glyphs."""
        set_id = str(uuid.uuid4())[:8]
        
        # Create copies of glyphs with new IDs
        copied_glyphs = [
            Glyph(
                id=str(uuid.uuid4())[:8],
                char=g.char,
                template=g.template,
                width=g.width,
                height=g.height,
                ignored=g.ignored if hasattr(g, 'ignored') else False
            )
            for g in glyphs
        ]
        
        glyph_set = GlyphSet(
            id=set_id,
            name=name,
            glyphs=copied_glyphs
        )
        self.glyph_sets[set_id] = glyph_set
        self.save_glyph_sets()
        return glyph_set
    
    def delete_glyph_set(self, set_id: str) -> bool:
        """Delete a glyph set by ID."""
        if set_id in self.glyph_sets:
            del self.glyph_sets[set_id]
            self.save_glyph_sets()
            return True
        return False
    
    def export_from_session(self, session_id: str, name: str) -> Optional[GlyphSet]:
        """Export glyphs from a session to a new glyph set."""
        session = session_manager.get_session(session_id)
        if session is None or not session.glyphs:
            return None
        
        return self.create_glyph_set(name, session.glyphs)
    
    def import_to_session(self, session_id: str, set_id: str, replace: bool = False) -> bool:
        """
        Import a glyph set into a session.
        
        Args:
            session_id: Target session ID
            set_id: Source glyph set ID
            replace: If True, replace existing glyphs. If False, append.
        
        Returns:
            True if successful, False otherwise.
        """
        session = session_manager.get_session(session_id)
        glyph_set = self.get_glyph_set(set_id)
        
        if session is None or glyph_set is None:
            return False
        
        # Create copies of glyphs with new IDs for the session
        new_glyphs = [
            Glyph(
                id=str(uuid.uuid4())[:8],
                char=g.char,
                template=g.template,
                width=g.width,
                height=g.height,
                ignored=g.ignored if hasattr(g, 'ignored') else False
            )
            for g in glyph_set.glyphs
        ]
        
        if replace:
            session.glyphs = new_glyphs
        else:
            session.glyphs.extend(new_glyphs)
        
        session_manager.save_sessions()
        return True


# Global instance
glyph_storage_manager = GlyphStorageManager()
