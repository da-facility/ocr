#!/bin/bash
# Build a .app bundle with ffmpeg that can request camera permissions

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="CameraTest"
APP_DIR="$SCRIPT_DIR/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

echo "Building $APP_NAME.app..."

# Clean previous build
rm -rf "$APP_DIR"

# Create app structure
mkdir -p "$MACOS_DIR"
mkdir -p "$RESOURCES_DIR"

# Download ffmpeg if not present
if [ ! -f "$SCRIPT_DIR/bin/ffmpeg" ]; then
    echo "Downloading ffmpeg..."
    mkdir -p "$SCRIPT_DIR/bin"
    curl -L "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip" -o /tmp/ffmpeg.zip
    unzip -o /tmp/ffmpeg.zip -d "$SCRIPT_DIR/bin"
    rm /tmp/ffmpeg.zip
fi

# Copy ffmpeg
cp "$SCRIPT_DIR/bin/ffmpeg" "$MACOS_DIR/ffmpeg"
chmod +x "$MACOS_DIR/ffmpeg"

# Create launcher script
cat > "$MACOS_DIR/$APP_NAME" << 'LAUNCHER'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/ffmpeg" "$@"
LAUNCHER
chmod +x "$MACOS_DIR/$APP_NAME"

# Create Info.plist
cat > "$CONTENTS_DIR/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>CameraTest</string>
    <key>CFBundleIdentifier</key>
    <string>com.test.cameratest</string>
    <key>CFBundleName</key>
    <string>CameraTest</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>NSCameraUsageDescription</key>
    <string>This app needs camera access to capture video frames.</string>
    <key>NSCameraUseContinuityCameraDeviceType</key>
    <true/>
</dict>
</plist>
PLIST

# Create entitlements
cat > /tmp/app-entitlements.plist << 'ENTITLEMENTS'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
    <key>com.apple.security.device.camera</key>
    <true/>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
</dict>
</plist>
ENTITLEMENTS

# Sign the app bundle
echo "Signing app bundle..."
codesign --remove-signature "$MACOS_DIR/ffmpeg" 2>/dev/null || true
codesign --force --sign - --entitlements /tmp/app-entitlements.plist "$MACOS_DIR/ffmpeg"
codesign --force --sign - --entitlements /tmp/app-entitlements.plist "$APP_DIR"

echo ""
echo "Done! App created at: $APP_DIR"
echo ""
echo "Test commands:"
echo "  List devices:"
echo "    $APP_DIR/Contents/MacOS/ffmpeg -hide_banner -f avfoundation -list_devices true -i \"\""
echo ""
echo "  Capture frame from camera 1:"
echo "    $APP_DIR/Contents/MacOS/ffmpeg -f avfoundation -i \"1:none\" -frames:v 1 test.png"
echo ""
echo "If prompted, grant camera permission to 'CameraTest' in System Settings."
