"""
Validators for OCR region types.
Apply validation and parsing to OCR results based on region type.
"""
from typing import Optional
import re


class ScoreValidator:
    """
    Validates score values, optionally enforcing +/-1 increments.
    
    - Strips all non-numeric characters from input
    - In singles mode, only accepts values that differ by at most 1 from the last value
    - Provides a reset method to clear the last value state
    - Returns structured result with is_stable flag indicating if value is fresh or cached
    
    Stateful: tracks the last stable value and returns it when "?" is detected
    in the input (indicating OCR uncertainty) or when a large jump occurs in singles mode.
    """
    
    def __init__(self, singles_mode: bool = False):
        self.singles_mode = singles_mode
        self.last_value: Optional[int] = None
    
    def validate(self, text: str) -> dict:
        """
        Validate and clean a score value.
        
        Args:
            text: Raw OCR text
            
        Returns:
            Dictionary with parsed score info:
            {
                "value": int or None,  # The numeric value
                "formatted": str,  # Formatted string representation
                "is_stable": bool,  # True if fresh reading, False if cached due to stability rules or "?"
                "raw": str  # Original input text
            }
        """
        if not text:
            return self._empty_result(is_stable=True)
        
        # Check for "?" indicating OCR uncertainty - return last stable result
        if '?' in text:
            if self.last_value is not None:
                return {
                    "value": self.last_value,
                    "formatted": str(self.last_value),
                    "is_stable": False,
                    "raw": text
                }
            return self._empty_result(is_stable=False)
        
        # Strip non-numeric characters
        digits = ''.join(c for c in text if c.isdigit())
        if not digits:
            # No digits found - return last value if available
            if self.last_value is not None:
                return {
                    "value": self.last_value,
                    "formatted": str(self.last_value),
                    "is_stable": False,
                    "raw": text
                }
            return self._empty_result(is_stable=True)
        
        value = int(digits)
        
        if self.singles_mode and self.last_value is not None:
            diff = abs(value - self.last_value)
            if diff > 1:
                # Reject large jumps, return last valid value with is_stable=False
                return {
                    "value": self.last_value,
                    "formatted": str(self.last_value),
                    "is_stable": False,
                    "raw": text
                }
        
        # Fresh valid reading
        self.last_value = value
        return {
            "value": value,
            "formatted": str(value),
            "is_stable": True,
            "raw": text
        }
    
    def _empty_result(self, is_stable: bool = True) -> dict:
        """Return an empty result when no valid score is available."""
        return {
            "value": None,
            "formatted": "",
            "is_stable": is_stable,
            "raw": ""
        }
    
    def reset(self):
        """Reset the validator state, allowing any value to be accepted."""
        self.last_value = None
    
    def set_singles_mode(self, enabled: bool):
        """Enable or disable singles mode."""
        self.singles_mode = enabled


class TimeValidator:
    """
    Parses time formats from OCR text.
    
    Handles two main formats:
    1. MM:SS or M:SS (colon present or implied) - minutes and seconds
    2. SS.ms (period present) - seconds and centiseconds/milliseconds
    
    When the colon is "vanishing" (common in seven-segment displays), 
    it may be absent. In this case:
    - Take the last 2 digits as seconds
    - Everything before is minutes
    
    Stateful: tracks the last stable result and returns it when "?" is detected
    in the input (indicating OCR uncertainty).
    
    Format options:
    - "m:ss" - single digit minutes (e.g., "1:23")
    - "mm:ss" - zero-padded minutes (e.g., "01:23")
    """
    
    def __init__(self, time_format: str = "m:ss"):
        self.last_stable_result: Optional[dict] = None
        self.time_format = time_format  # "m:ss" or "mm:ss"
    
    def set_format(self, time_format: str):
        """Set the time format ("m:ss" or "mm:ss")."""
        self.time_format = time_format
    
    def validate(self, text: str) -> dict:
        """
        Parse a time value from OCR text.
        
        Args:
            text: Raw OCR text (e.g., "12:34", "1234", "10.45")
            
        Returns:
            Dictionary with parsed time components:
            {
                "minutes": int,
                "seconds": int,
                "centiseconds": int,  # hundredths of a second (0-99)
                "raw": str,  # cleaned input
                "formatted": str,  # formatted output like "12:34" or "10.45"
                "total_seconds": float,  # total time in seconds
                "is_stable": bool  # True if fresh reading, False if cached due to "?"
            }
        """
        if not text:
            return self._empty_result(is_stable=True)
        
        # Check for "?" indicating OCR uncertainty - return last stable result
        if '?' in text:
            if self.last_stable_result:
                return {**self.last_stable_result, "is_stable": False}
            return self._empty_result(is_stable=False)
        
        # Clean the text: keep only digits, colons, and periods
        cleaned = ''.join(c for c in text if c.isdigit() or c in ':.')
        if not cleaned:
            return self._empty_result(is_stable=True)
        
        # Check for period (SS.ms format)
        if '.' in cleaned:
            result = self._parse_seconds_millis(cleaned)
        # Check for colon (MM:SS format)
        elif ':' in cleaned:
            result = self._parse_minutes_seconds_with_colon(cleaned)
        else:
            # No separator - assume vanishing colon (MMSS format)
            result = self._parse_minutes_seconds_no_colon(cleaned)
        
        # Store as last stable result and mark as stable
        result["is_stable"] = True
        self.last_stable_result = result
        return result
    
    def reset(self):
        """Reset the validator state, clearing the last stable result."""
        self.last_stable_result = None
    
    def _format_minutes(self, minutes: int) -> str:
        """Format minutes according to the time_format setting."""
        if self.time_format == "mm:ss":
            return f"{minutes:02d}"
        return str(minutes)
    
    def _empty_result(self, is_stable: bool = True) -> dict:
        return {
            "minutes": 0,
            "seconds": 0,
            "centiseconds": 0,
            "raw": "",
            "formatted": f"{self._format_minutes(0)}:00",
            "total_seconds": 0.0,
            "is_stable": is_stable
        }
    
    def _parse_minutes_seconds_with_colon(self, text: str) -> dict:
        """Parse MM:SS or M:SS format."""
        parts = text.split(':')
        if len(parts) != 2:
            return self._empty_result()
        
        try:
            minutes = int(parts[0]) if parts[0] else 0
            seconds = int(parts[1]) if parts[1] else 0
            
            # Clamp seconds to valid range
            if seconds >= 60:
                minutes += seconds // 60
                seconds = seconds % 60
            
            total = minutes * 60 + seconds
            
            return {
                "minutes": minutes,
                "seconds": seconds,
                "centiseconds": 0,
                "raw": text,
                "formatted": f"{self._format_minutes(minutes)}:{seconds:02d}",
                "total_seconds": float(total)
            }
        except ValueError:
            return self._empty_result()
    
    def _parse_minutes_seconds_no_colon(self, text: str) -> dict:
        """Parse MMSS format (vanishing colon)."""
        digits = ''.join(c for c in text if c.isdigit())
        if not digits:
            return self._empty_result()
        
        try:
            if len(digits) <= 2:
                # Just seconds
                seconds = int(digits)
                minutes = 0
            else:
                # Last 2 digits are seconds, rest is minutes
                seconds = int(digits[-2:])
                minutes = int(digits[:-2])
            
            # Handle seconds overflow
            if seconds >= 60:
                minutes += seconds // 60
                seconds = seconds % 60
            
            total = minutes * 60 + seconds
            
            return {
                "minutes": minutes,
                "seconds": seconds,
                "centiseconds": 0,
                "raw": text,
                "formatted": f"{self._format_minutes(minutes)}:{seconds:02d}",
                "total_seconds": float(total)
            }
        except ValueError:
            return self._empty_result()
    
    def _parse_seconds_millis(self, text: str) -> dict:
        """Parse SS.ms format (seconds.centiseconds)."""
        parts = text.split('.')
        if len(parts) != 2:
            return self._empty_result()
        
        try:
            # Up to 2 digits for seconds
            seconds_str = parts[0][-2:] if len(parts[0]) > 2 else parts[0]
            seconds = int(seconds_str) if seconds_str else 0
            
            # Up to 2 digits for centiseconds (hundredths)
            cs_str = parts[1][:2] if len(parts[1]) >= 2 else parts[1].ljust(2, '0')
            centiseconds = int(cs_str) if cs_str else 0
            
            # Calculate total seconds
            total = seconds + (centiseconds / 100.0)
            
            # Convert to minutes:seconds if seconds >= 60
            minutes = seconds // 60
            display_seconds = seconds % 60
            
            if minutes > 0:
                formatted = f"{self._format_minutes(minutes)}:{display_seconds:02d}.{centiseconds:02d}"
            else:
                formatted = f"{display_seconds}.{centiseconds:02d}"
            
            return {
                "minutes": minutes,
                "seconds": display_seconds,
                "centiseconds": centiseconds,
                "raw": text,
                "formatted": formatted,
                "total_seconds": float(total)
            }
        except ValueError:
            return self._empty_result()


class GenericValidator:
    """
    Generic validator that passes through text with minimal processing.
    Just cleans up whitespace.
    """
    
    def validate(self, text: str) -> str:
        """Return cleaned text."""
        if not text:
            return ""
        return text.strip()
