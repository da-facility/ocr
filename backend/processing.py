
import cv2
import numpy as np


def apply_perspective_transform(frame: np.ndarray, 
                                 points: list[tuple[int, int]],
                                 output_size: tuple[int, int] = (800, 600)) -> np.ndarray:
    """
    Apply perspective transform using 4 source points.
    Points should be in order: top-left, top-right, bottom-right, bottom-left
    """
    if len(points) != 4:
        return frame
    
    src_points = np.float32(points)
    
    dst_points = np.float32([
        [0, 0],
        [output_size[0], 0],
        [output_size[0], output_size[1]],
        [0, output_size[1]]
    ])
    
    matrix = cv2.getPerspectiveTransform(src_points, dst_points)
    warped = cv2.warpPerspective(frame, matrix, output_size)
    
    return warped


def apply_color_filters_binary(frame: np.ndarray, color_filters: list[dict]) -> np.ndarray:
    """
    Apply multiple color filters and return a binary mask.
    Each filter has: bgr (color), tolerance (per-channel tolerance)
    Returns binary image: white (#ffffff) where pixels match ANY color, black (#000000) elsewhere.
    """
    if not color_filters:
        # No filters - return grayscale converted to binary (for OCR compatibility)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
        return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    
    combined_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    
    for cf in color_filters:
        bgr = np.array(cf['bgr'], dtype=np.int32)
        tolerance = np.array(cf['tolerance'], dtype=np.int32)
        
        lower = np.clip(bgr - tolerance, 0, 255).astype(np.uint8)
        upper = np.clip(bgr + tolerance, 0, 255).astype(np.uint8)
        
        mask = cv2.inRange(frame, lower, upper)
        combined_mask = cv2.bitwise_or(combined_mask, mask)
    
    # Convert to 3-channel binary (pure black #000000 and white #ffffff)
    binary_3ch = cv2.cvtColor(combined_mask, cv2.COLOR_GRAY2BGR)
    return binary_3ch


def apply_erosion(frame: np.ndarray, kernel_size: int) -> np.ndarray:
    """Apply morphological erosion to shrink white regions. 0 or 1 = off."""
    if kernel_size <= 1:
        return frame
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    return cv2.erode(frame, kernel, iterations=1)


def apply_dilation(frame: np.ndarray, kernel_size: int) -> np.ndarray:
    """Apply morphological dilation to expand/connect white regions. 0 or 1 = off."""
    if kernel_size <= 1:
        return frame
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    return cv2.dilate(frame, kernel, iterations=1)


def get_color_at_point(frame: np.ndarray, x: int, y: int) -> list[int]:
    """Get BGR color at a specific point in the frame."""
    h, w = frame.shape[:2]
    x = max(0, min(x, w - 1))
    y = max(0, min(y, h - 1))
    bgr = frame[y, x].tolist()
    return bgr


def process_frame_perspective(frame: np.ndarray,
                              perspective_points: list[tuple[int, int]] | None = None,
                              output_size: tuple[int, int] = (800, 600)) -> np.ndarray:
    """Apply only perspective correction."""
    if perspective_points and len(perspective_points) == 4:
        return apply_perspective_transform(frame, perspective_points, output_size)
    return frame


def process_frame_full(frame: np.ndarray,
                       perspective_points: list[tuple[int, int]] | None = None,
                       output_size: tuple[int, int] = (800, 600),
                       color_filters: list[dict] | None = None,
                       erosion_kernel: int = 1,
                       dilation_kernel: int = 1) -> np.ndarray:
    """
    Full processing pipeline: perspective -> color filters (binary) -> morphology
    
    Output is a pure black and white image:
    - White (#ffffff): pixels matching any color filter
    - Black (#000000): everything else
    """
    result = frame.copy()
    
    # Step 1: Perspective correction
    if perspective_points and len(perspective_points) == 4:
        result = apply_perspective_transform(result, perspective_points, output_size)
    
    # Step 2: Color filtering to binary (if filters exist)
    if color_filters:
        # Convert to binary based on color filters
        result = apply_color_filters_binary(result, color_filters)
        
        # Step 3: Morphology on binary image
        # Erosion first (removes noise, shrinks regions) - 0 or 1 = off
        if erosion_kernel > 1:
            result = apply_erosion(result, erosion_kernel)
        
        # Dilation second (expands regions, connects nearby pixels) - 0 or 1 = off
        if dilation_kernel > 1:
            result = apply_dilation(result, dilation_kernel)
    
    return result


def frame_to_jpeg(frame: np.ndarray, quality: int = 80) -> bytes:
    """Convert frame to JPEG bytes."""
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    _, buffer = cv2.imencode('.jpg', frame, encode_param)
    return buffer.tobytes()
