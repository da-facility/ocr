"""
Glyph-based OCR using template matching.
Detects connected components (glyphs) and matches them against stored templates.
"""
import cv2
import numpy as np
from typing import Optional

# Normalized glyph size for template matching
GLYPH_SIZE = (32, 48)  # width, height


def merge_vertical_glyphs(glyphs: list[dict], binary_image: np.ndarray,
                          x_tolerance: float = 0.5, gap_ratio: float = 2.0) -> list[dict]:
    """
    Merge glyphs that are vertically stacked (like the dots in a colon ':').
    
    Args:
        glyphs: List of detected glyphs
        binary_image: Original binary image to extract merged glyph from
        x_tolerance: How much x-centers can differ as a fraction of avg width
        gap_ratio: Max vertical gap as a ratio of avg glyph height
    
    Returns:
        List of glyphs with vertically stacked ones merged
    """
    if len(glyphs) < 2:
        return glyphs
    
    # Ensure single channel
    if len(binary_image.shape) == 3:
        gray = cv2.cvtColor(binary_image, cv2.COLOR_BGR2GRAY)
    else:
        gray = binary_image
    
    merged = []
    used = set()
    
    for i, g1 in enumerate(glyphs):
        if i in used:
            continue
        
        # Find glyphs that could be vertically stacked with this one
        stack = [g1]
        stack_indices = [i]
        
        for j, g2 in enumerate(glyphs):
            if j <= i or j in used:
                continue
            
            # Check if centers are horizontally aligned
            c1_x = g1['x'] + g1['width'] / 2
            c2_x = g2['x'] + g2['width'] / 2
            avg_width = (g1['width'] + g2['width']) / 2
            
            if abs(c1_x - c2_x) > avg_width * x_tolerance:
                continue
            
            # Check if they're vertically close (not too far apart)
            g1_bottom = g1['y'] + g1['height']
            g2_top = g2['y']
            avg_height = (g1['height'] + g2['height']) / 2
            
            # Check gap between bottom of upper and top of lower
            min_top = min(g['y'] for g in stack)
            max_bottom = max(g['y'] + g['height'] for g in stack)
            
            if g2['y'] >= max_bottom:  # g2 is below the stack
                gap = g2['y'] - max_bottom
                if gap <= avg_height * gap_ratio:
                    stack.append(g2)
                    stack_indices.append(j)
            elif g2['y'] + g2['height'] <= min_top:  # g2 is above the stack
                gap = min_top - (g2['y'] + g2['height'])
                if gap <= avg_height * gap_ratio:
                    stack.append(g2)
                    stack_indices.append(j)
        
        if len(stack) > 1:
            # Merge into a single glyph
            min_x = min(g['x'] for g in stack)
            min_y = min(g['y'] for g in stack)
            max_x = max(g['x'] + g['width'] for g in stack)
            max_y = max(g['y'] + g['height'] for g in stack)
            
            merged_img = gray[min_y:max_y, min_x:max_x].copy()
            total_area = sum(g['area'] for g in stack)
            
            merged.append({
                'x': int(min_x),
                'y': int(min_y),
                'width': int(max_x - min_x),
                'height': int(max_y - min_y),
                'area': float(total_area),
                'image': merged_img,
                'merged_count': len(stack)
            })
            used.update(stack_indices)
        else:
            merged.append(g1)
            used.add(i)
    
    # Re-sort by x position
    merged.sort(key=lambda g: g['x'])
    return merged


def find_glyphs(binary_image: np.ndarray, min_area: int = 50, 
                merge_vertical: bool = False) -> list[dict]:
    """
    Find all connected components (glyphs) in a binary image.
    Returns list of glyphs sorted left-to-right with their bounding boxes and images.
    
    Args:
        binary_image: Binary image (white content on black background)
        min_area: Minimum pixel area to consider as a glyph
        merge_vertical: If True, merge vertically stacked glyphs (like ':')
    
    Returns:
        List of dicts with keys: x, y, width, height, image (cropped glyph)
    """
    # Ensure single channel
    if len(binary_image.shape) == 3:
        gray = cv2.cvtColor(binary_image, cv2.COLOR_BGR2GRAY)
    else:
        gray = binary_image.copy()
    
    # Find contours
    contours, _ = cv2.findContours(gray, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    glyphs = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        
        x, y, w, h = cv2.boundingRect(contour)
        
        # Extract the glyph image
        glyph_img = gray[y:y+h, x:x+w].copy()
        
        # Convert numpy types to Python native for JSON serialization
        glyphs.append({
            'x': int(x),
            'y': int(y),
            'width': int(w),
            'height': int(h),
            'area': float(area),
            'image': glyph_img
        })
    
    # Sort by x position (left to right)
    glyphs.sort(key=lambda g: g['x'])
    
    # Optionally merge vertically stacked glyphs
    if merge_vertical:
        glyphs = merge_vertical_glyphs(glyphs, binary_image)
    
    return glyphs


def normalize_glyph(glyph_image: np.ndarray, size: tuple[int, int] = GLYPH_SIZE) -> np.ndarray:
    """
    Normalize a glyph image to a fixed size for template matching.
    Maintains aspect ratio and centers the glyph.
    """
    h, w = glyph_image.shape[:2]
    target_w, target_h = size
    
    # Calculate scale to fit while maintaining aspect ratio
    scale = min(target_w / w, target_h / h) * 0.8  # 80% to leave some padding
    
    new_w = int(w * scale)
    new_h = int(h * scale)
    
    # Resize
    resized = cv2.resize(glyph_image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    
    # Create canvas and center the glyph
    canvas = np.zeros((target_h, target_w), dtype=np.uint8)
    x_offset = (target_w - new_w) // 2
    y_offset = (target_h - new_h) // 2
    canvas[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized
    
    return canvas


def glyph_to_template(glyph_image: np.ndarray) -> list[list[int]]:
    """Convert a glyph image to a template (2D list of pixel values)."""
    normalized = normalize_glyph(glyph_image)
    return normalized.tolist()


def template_to_image(template: list[list[int]]) -> np.ndarray:
    """Convert a template back to a numpy image."""
    return np.array(template, dtype=np.uint8)


def match_glyph(glyph_image: np.ndarray, templates: list[dict], 
                threshold: float = 0.7) -> Optional[tuple[str, float]]:
    """
    Match a glyph image against stored templates.
    
    Args:
        glyph_image: The glyph image to match
        templates: List of dicts with 'char' and 'template' keys
        threshold: Minimum match score (0-1) to consider a match
    
    Returns:
        Tuple of (matched_char, confidence) or None if no match
    """
    if not templates:
        return None
    
    normalized = normalize_glyph(glyph_image)
    
    best_match = None
    best_score = threshold
    
    for template_data in templates:
        template_img = template_to_image(template_data['template'])
        
        # Use normalized cross-correlation for matching
        result = cv2.matchTemplate(normalized, template_img, cv2.TM_CCOEFF_NORMED)
        score = result[0, 0]  # Single value since same size
        
        if score > best_score:
            best_score = score
            best_match = template_data['char']
    
    if best_match:
        return (best_match, float(best_score))  # Convert numpy float to Python float
    return None


def recognize_with_glyphs(binary_image: np.ndarray, templates: list[dict], 
                          min_area: int = 50, merge_vertical: bool = True,
                          threshold: float = 0.7) -> list[dict]:
    """
    Perform OCR using glyph template matching.
    
    Args:
        binary_image: Binary image (white content on black background)
        templates: List of glyph templates from session
        min_area: Minimum pixel area for glyph detection
        merge_vertical: If True, auto-merge vertically stacked glyphs
        threshold: Minimum match score (0-1) to consider a match
    
    Returns:
        List of recognized characters with bounding boxes and confidence
    """
    # Filter out ignored templates
    active_templates = [t for t in templates if not t.get('ignored', False)]
    
    threshold = max(0.0, min(1.0, float(threshold)))
    glyphs = find_glyphs(binary_image, min_area, merge_vertical=merge_vertical)
    
    results = []
    for glyph in glyphs:
        match = match_glyph(glyph['image'], active_templates, threshold=threshold)
        
        if match:
            char, confidence = match
            # Check if this matched an ignored glyph (skip it from output)
            matched_template = next((t for t in templates if t['char'] == char), None)
            if matched_template and matched_template.get('ignored', False):
                # Skip ignored glyphs entirely (don't add to results)
                continue
            results.append({
                'char': char,
                'confidence': float(confidence),  # Ensure Python float
                'x': int(glyph['x']),
                'y': int(glyph['y']),
                'width': int(glyph['width']),
                'height': int(glyph['height'])
            })
        else:
            # Unknown glyph
            results.append({
                'char': '?',
                'confidence': 0.0,
                'x': int(glyph['x']),
                'y': int(glyph['y']),
                'width': int(glyph['width']),
                'height': int(glyph['height'])
            })
    
    return results


def glyphs_to_text(results: list[dict]) -> str:
    """Convert glyph recognition results to a string."""
    return ''.join(r['char'] for r in results)


def get_detected_glyphs_for_training(binary_image: np.ndarray, 
                                      min_area: int = 50,
                                      merge_vertical: bool = False) -> list[dict]:
    """
    Get detected glyphs for the training UI.
    Returns glyphs with their normalized templates ready for labeling.
    
    Args:
        binary_image: Binary image to detect glyphs in
        min_area: Minimum pixel area for glyph detection
        merge_vertical: If True, auto-merge vertically stacked glyphs
    """
    glyphs = find_glyphs(binary_image, min_area, merge_vertical=merge_vertical)
    
    result = []
    for i, glyph in enumerate(glyphs):
        template = glyph_to_template(glyph['image'])
        # Convert numpy arrays to Python native types for JSON serialization
        result.append({
            'index': i,
            'x': int(glyph['x']),
            'y': int(glyph['y']),
            'width': int(glyph['width']),
            'height': int(glyph['height']),
            'merged_count': glyph.get('merged_count', 1),
            'template': [[int(pixel) for pixel in row] for row in template]
        })
    
    return result


def combine_glyphs_by_indices(binary_image: np.ndarray, indices: list[int],
                               min_area: int = 50) -> Optional[dict]:
    """
    Manually combine specific detected glyphs by their indices.
    Used when the user selects multiple glyphs to combine in the training UI.
    
    Args:
        binary_image: Binary image to detect glyphs in
        indices: List of glyph indices to combine
        min_area: Minimum pixel area for initial detection
    
    Returns:
        Combined glyph dict with template, or None if invalid indices
    """
    if len(indices) < 1:
        return None
    
    # Get all glyphs without merging
    glyphs = find_glyphs(binary_image, min_area, merge_vertical=False)
    
    # Validate indices
    if any(i < 0 or i >= len(glyphs) for i in indices):
        return None
    
    selected = [glyphs[i] for i in indices]
    
    if len(selected) == 1:
        # Single glyph
        glyph = selected[0]
        template = glyph_to_template(glyph['image'])
        return {
            'x': int(glyph['x']),
            'y': int(glyph['y']),
            'width': int(glyph['width']),
            'height': int(glyph['height']),
            'merged_count': 1,
            'template': [[int(pixel) for pixel in row] for row in template]
        }
    
    # Combine multiple glyphs
    # Ensure single channel
    if len(binary_image.shape) == 3:
        gray = cv2.cvtColor(binary_image, cv2.COLOR_BGR2GRAY)
    else:
        gray = binary_image
    
    min_x = min(g['x'] for g in selected)
    min_y = min(g['y'] for g in selected)
    max_x = max(g['x'] + g['width'] for g in selected)
    max_y = max(g['y'] + g['height'] for g in selected)
    
    combined_img = gray[min_y:max_y, min_x:max_x].copy()
    template = glyph_to_template(combined_img)
    
    return {
        'x': int(min_x),
        'y': int(min_y),
        'width': int(max_x - min_x),
        'height': int(max_y - min_y),
        'merged_count': len(selected),
        'template': [[int(pixel) for pixel in row] for row in template]
    }
