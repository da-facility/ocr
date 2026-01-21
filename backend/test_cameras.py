#!/usr/bin/env python3
import re
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "debug" / "pngs"


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def list_ffmpeg_video_devices() -> list[dict[str, str]]:
    result = run_command(
        ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
    )
    output = result.stderr
    devices: list[dict[str, str]] = []
    in_video_section = False

    for line in output.splitlines():
        if "AVFoundation video devices:" in line:
            in_video_section = True
            continue
        if "AVFoundation audio devices:" in line:
            in_video_section = False
            continue
        if not in_video_section:
            continue

        match = re.search(r"\[(\d+)\]\s+(.+)$", line)
        if match:
            devices.append({"index": match.group(1), "name": match.group(2).strip()})

    return devices


def _safe_av_attr(obj, name: str):
    try:
        value = getattr(obj, name)
        return value() if callable(value) else value
    except Exception:
        return None


def list_video_devices() -> list[dict[str, str | None]]:
    try:
        import AVFoundation
    except ImportError:
        print("PyObjC not installed. Run: pip install pyobjc-framework-AVFoundation")
        return []

    ffmpeg_devices = list_ffmpeg_video_devices()
    ffmpeg_by_name: dict[str, list[str]] = {}
    for device in ffmpeg_devices:
        key = device["name"].lower()
        ffmpeg_by_name.setdefault(key, []).append(device["index"])

    device_types = [
        AVFoundation.AVCaptureDeviceTypeBuiltInWideAngleCamera,
        AVFoundation.AVCaptureDeviceTypeExternalUnknown,
    ]
    continuity_type = getattr(AVFoundation, "AVCaptureDeviceTypeContinuityCamera", None)
    if continuity_type is not None:
        device_types.append(continuity_type)

    discovery_cls = getattr(AVFoundation, "AVCaptureDeviceDiscoverySession", None)
    if discovery_cls is None:
        print("AVFoundation discovery session not available.")
        return []

    discovery = discovery_cls.discoverySessionWithDeviceTypes_mediaType_position_(
        device_types,
        AVFoundation.AVMediaTypeVideo,
        AVFoundation.AVCaptureDevicePositionUnspecified,
    )
    devices = []
    for device in discovery.devices():
        name = _safe_av_attr(device, "localizedName") or "Unknown Camera"
        model_id = _safe_av_attr(device, "modelID")
        device_type = _safe_av_attr(device, "deviceType")
        unique_id = _safe_av_attr(device, "uniqueID")

        continuity = False
        if isinstance(model_id, str) and model_id.startswith(("iPhone", "iPad")):
            continuity = True
        if continuity_type is not None and device_type == continuity_type:
            continuity = True

        is_facetime_hd = (
            device_type == AVFoundation.AVCaptureDeviceTypeBuiltInWideAngleCamera
            and model_id == "FaceTime HD Camera"
        )
        kind = "facetime_hd" if is_facetime_hd else ("continuity" if continuity else "normal")

        key = name.lower()
        index = None
        if key in ffmpeg_by_name and ffmpeg_by_name[key]:
            index = ffmpeg_by_name[key].pop(0)

        devices.append(
            {
                "index": index,
                "name": name,
                "model_id": model_id,
                "unique_id": unique_id,
                "device_type": device_type,
                "continuity": "yes" if continuity else "no",
                "kind": kind,
            }
        )

    return devices


def should_capture_all() -> bool:
    prompt = "Capture snapshot from all cameras? [Y/n] "
    response = input(prompt).strip().lower()
    return response in {"", "y", "yes"}


def sanitize_filename(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return sanitized or "camera"


COMMON_FPS = ["60", "30", "24", "15", "10", "1"]


def build_attempts(name: str) -> list[dict[str, str | None]]:
    attempts: list[dict[str, str | None]] = []

    if "FaceTime" in name:
        # FaceTime HD Camera often only accepts exact 60fps modes.
        attempts.append(
            {
                "video_size": "1920x1080",
                "framerate": "60",
                "pixel_format": None,
                "reason": "hardcoded: FaceTime fix (1080p60 default)",
            }
        )
        for pixel_format in ["uyvy422", "nv12", "yuyv422", "yuv420p"]:
            attempts.append(
                {
                    "video_size": "1920x1080",
                    "framerate": "60",
                    "pixel_format": pixel_format,
                    "reason": f"hardcoded: FaceTime fix (1080p60 {pixel_format})",
                }
            )
        attempts.append(
            {
                "video_size": "1280x720",
                "framerate": "60",
                "pixel_format": None,
                "reason": "hardcoded: FaceTime fix (720p60 default)",
            }
        )
        for pixel_format in ["uyvy422", "nv12", "yuyv422", "yuv420p"]:
            attempts.append(
                {
                    "video_size": "1280x720",
                    "framerate": "60",
                    "pixel_format": pixel_format,
                    "reason": f"hardcoded: FaceTime fix (720p60 {pixel_format})",
                }
            )

    for size, reason in (
        ("1920x1080", "fallback: 1080p common fps"),
        ("1280x720", "fallback: 720p common fps"),
        ("640x480", "fallback: 480p common fps"),
    ):
        for fps in COMMON_FPS:
            attempts.append(
                {
                    "video_size": size,
                    "framerate": fps,
                    "pixel_format": None,
                    "reason": reason,
                }
            )

    attempts.append(
        {
            "video_size": None,
            "framerate": None,
            "pixel_format": None,
            "reason": "fallback: device default",
        }
    )

    return attempts


def should_skip_device(name: str) -> bool:
    lowered = name.lower()
    return "capture screen" in lowered or "screen capture" in lowered


def capture_snapshot(index: str, name: str, output_dir: Path) -> tuple[bool, str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{int(index):02d}_{sanitize_filename(name)}.png"
    output_path = output_dir / filename

    for attempt in build_attempts(name):
        cmd = ["ffmpeg", "-y", "-f", "avfoundation"]
        if attempt["video_size"]:
            cmd += ["-video_size", str(attempt["video_size"])]
        if attempt["framerate"]:
            cmd += ["-framerate", str(attempt["framerate"])]
        if attempt["pixel_format"]:
            cmd += ["-pixel_format", str(attempt["pixel_format"])]

        cmd += ["-i", index, "-frames:v", "1", str(output_path)]
        result = run_command(cmd)
        if result.returncode == 0:
            parts = []
            if attempt["video_size"]:
                parts.append(str(attempt["video_size"]))
            if attempt["framerate"]:
                parts.append(f"{attempt['framerate']}fps")
            if attempt["pixel_format"]:
                parts.append(str(attempt["pixel_format"]))
            mode = "@".join(parts) if parts else "device default"
            print(f"Saved: {output_path}")
            return True, mode, str(attempt["reason"])

    print(f"Failed to capture from '{name}'.")
    print(result.stderr.strip())
    return False, "unknown", "all attempts failed"


def main() -> int:
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found in PATH.")
        print("Run: backend/setup_ffmpeg.sh")
        return 1

    devices = list_video_devices()
    if not devices:
        print("No video devices found.")
        return 1

    print("Detected video devices:")
    for device in devices:
        index = device["index"] if device["index"] is not None else "?"
        continuity = " continuity" if device.get("continuity") == "yes" else ""
        model_id = device.get("model_id")
        model_label = f" model={model_id}" if model_id else ""
        kind = device.get("kind") or "normal"
        kind_label = f" kind={kind}"
        print(f"  [{index}] {device['name']}{continuity}{model_label}{kind_label}")

    if not should_capture_all():
        return 0

    summary: list[str] = []

    for idx, device in enumerate(devices):
        if idx > 0:
            print("")
        if should_skip_device(device["name"]):
            summary.append(f"{device['name']}: skipped (screen capture)")
            continue
        if device["index"] is None:
            summary.append(f"{device['name']}: skipped (no ffmpeg index match)")
            continue
        success, mode, reason = capture_snapshot(
            device["index"], device["name"], OUTPUT_DIR
        )
        status = "ok" if success else "failed"
        summary.append(f"{device['name']}: {mode} ({reason}) [{status}]")

    if summary:
        print("")
        print("Summary:")
        for line in summary:
            print(f"  {line}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
