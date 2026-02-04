"""
Request camera permission on macOS using native APIs.
Run this first to trigger the permission dialog.
"""

import platform

if platform.system() != "Darwin":
    print("This script is for macOS only")
    exit(1)

try:
    import AVFoundation
    from Foundation import NSDate, NSRunLoop
except ImportError:
    print("PyObjC not installed. Run: pip install pyobjc-framework-AVFoundation")
    exit(1)


def request_camera_permission():
    """Request camera permission and wait for response."""
    
    # Check current status
    status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
        AVFoundation.AVMediaTypeVideo
    )
    
    status_names = {
        0: "Not Determined",
        1: "Restricted", 
        2: "Denied",
        3: "Authorized"
    }
    
    print(f"Current camera permission status: {status_names.get(status, 'Unknown')}")
    
    if status == 3:  # Authorized
        print("✓ Camera access already granted!")
        return True
    
    if status == 2:  # Denied
        print("✗ Camera access denied. Enable in System Settings → Privacy & Security → Camera")
        return False
    
    if status == 1:  # Restricted
        print("✗ Camera access restricted by system policy")
        return False
    
    # Not determined - request permission
    print("Requesting camera permission...")
    
    result = [None]
    
    def callback(granted):
        result[0] = granted
    
    AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
        AVFoundation.AVMediaTypeVideo,
        callback
    )
    
    # Wait for callback
    timeout = 60  # seconds
    start = NSDate.date()
    while result[0] is None:
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.1)
        )
        if NSDate.date().timeIntervalSinceDate_(start) > timeout:
            print("Timeout waiting for permission response")
            return False
    
    if result[0]:
        print("✓ Camera access granted!")
        return True
    else:
        print("✗ Camera access denied by user")
        return False


if __name__ == "__main__":
    request_camera_permission()
