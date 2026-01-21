"""
Test script to enumerate cameras using ffmpeg and capture screenshots.
Run: python test_cameras.py
"""

import subprocess
import re
import os
import platform


def get_ffmpeg_path() -> str:
    """Get ffmpeg path - prefer app bundle, then bin, then system."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Prefer app bundle (has proper camera entitlements)
    app_ffmpeg = os.path.join(script_dir, "CameraTest.app", "Contents", "MacOS", "ffmpeg")
    if os.path.exists(app_ffmpeg):
        return app_ffmpeg
    
    # Fall back to bin
    bundled = os.path.join(script_dir, "bin", "ffmpeg")
    if os.path.exists(bundled):
        return bundled
    
    return "ffmpeg"


def list_cameras_ffmpeg() -> list[tuple[int, str]]:
    """Use ffmpeg to list video devices. Returns [(index, name), ...]"""
    system = platform.system()
    ffmpeg = get_ffmpeg_path()
    
    try:
        if system == "Windows":
            cmd = [ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"]
        elif system == "Darwin":
            cmd = [ffmpeg, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
        else:
            cmd = [ffmpeg, "-hide_banner", "-f", "v4l2", "-list_devices", "true", "-i", ""]
        
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        output = result.stderr
        
        if system == "Windows":
            pattern = re.compile(r'\[dshow.*?\]\s+"([^"]+)"\s+\(video\)')
            names = pattern.findall(output)
            return [(i, name) for i, name in enumerate(names)]
            
        elif system == "Darwin":
            cameras = []
            in_video_section = False
            for line in output.splitlines():
                if "AVFoundation video devices:" in line:
                    in_video_section = True
                    continue
                if "AVFoundation audio devices:" in line:
                    break
                if in_video_section:
                    match = re.search(r'\[(\d+)\]\s+(.+)$', line)
                    if match:
                        idx = int(match.group(1))
                        name = match.group(2).strip()
                        if not name.lower().startswith("capture screen"):
                            cameras.append((idx, name))
            return cameras
            
        else:
            pattern = re.compile(r'\[v4l2.*?\]\s+(.+?)\s+\(')
            names = pattern.findall(output)
            return [(i, name) for i, name in enumerate(names)]
            
    except FileNotFoundError:
        print("Error: ffmpeg not found")
        return []


def sanitize_filename(name: str) -> str:
    """Remove characters not allowed in filenames."""
    return re.sub(r'[<>:"/\\|?*]', '_', name)


def capture_ffmpeg(index: int, name: str, filepath: str) -> tuple[bool, str]:
    """Capture a single frame with ffmpeg."""
    system = platform.system()
    ffmpeg = get_ffmpeg_path()
    
    try:
        if system == "Windows":
            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "dshow",
                "-i", f"video={name}",
                "-frames:v", "1",
                filepath
            ]
        elif system == "Darwin":
            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "avfoundation",
                "-framerate", "30",
                "-i", f"{index}:none",
                "-frames:v", "1",
                filepath
            ]
        else:
            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "v4l2",
                "-i", f"/dev/video{index}",
                "-frames:v", "1",
                filepath
            ]
        
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=10,
        )
        
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            return True, ""
        
        err = result.stderr.strip()
        return False, err if err else "Failed"
        
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)


def main():
    ffmpeg = get_ffmpeg_path()
    print(f"Platform: {platform.system()}")
    print(f"ffmpeg: {ffmpeg}")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    app_exists = os.path.exists(os.path.join(script_dir, "CameraTest.app"))
    
    if platform.system() == "Darwin" and not app_exists:
        print("\n⚠️  CameraTest.app not found. Run: ./build_camera_app.sh")
        print("   This creates an app bundle with proper camera permissions.\n")
    
    print("Scanning for cameras...")
    
    cameras = list_cameras_ffmpeg()
    
    if not cameras:
        print("No cameras detected.")
        return
    
    print(f"\n{len(cameras)} cameras detected:")
    for idx, name in cameras:
        print(f"  [{idx}] {name}")
    
    print()
    response = input("Take a screenshot of each? [y/N] ").strip().lower()
    
    if response != 'y':
        print("Exiting.")
        return
    
    output_dir = os.path.join(script_dir, "pngs")
    os.makedirs(output_dir, exist_ok=True)
    print(f"\nSaving to: {output_dir}\n")
    
    for idx, name in cameras:
        filename = f"{sanitize_filename(name)}.png"
        filepath = os.path.join(output_dir, filename)
        print(f"Capturing [{idx}] {name}...", end=" ", flush=True)
        success, error = capture_ffmpeg(idx, name, filepath)
        if success:
            print(f"OK -> pngs/{filename}")
        else:
            print(f"FAILED ({error})")
    
    print("\nDone.")


if __name__ == "__main__":
    main()
