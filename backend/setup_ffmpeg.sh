#!/bin/bash
# Download and sign ffmpeg with camera entitlements

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$SCRIPT_DIR/bin"

mkdir -p "$BIN_DIR"

echo "Downloading ffmpeg static build..."
curl -L "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip" -o /tmp/ffmpeg.zip

echo "Extracting..."
unzip -o /tmp/ffmpeg.zip -d "$BIN_DIR"
rm /tmp/ffmpeg.zip

echo "Creating entitlements..."
cat > /tmp/ffmpeg-entitlements.plist << 'EOF'
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
EOF

echo "Removing existing signature..."
codesign --remove-signature "$BIN_DIR/ffmpeg" 2>/dev/null || true

echo "Signing with entitlements..."
codesign --force --sign - --entitlements /tmp/ffmpeg-entitlements.plist "$BIN_DIR/ffmpeg"

echo "Verifying..."
codesign -dvv "$BIN_DIR/ffmpeg"

echo ""
echo "Done! ffmpeg installed at: $BIN_DIR/ffmpeg"
echo "Test with: $BIN_DIR/ffmpeg -f avfoundation -list_devices true -i \"\""
