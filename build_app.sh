#!/bin/bash
# Build a MOVEABLE, double-clickable PalmClix.app on the user's own Mac.
# The compiled Swift executable, bundled Python helper, and libusb are inside.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo 'PalmClix.app must be compiled on macOS (AppKit is unavailable elsewhere).' >&2
  exit 1
fi
command -v swift >/dev/null || { echo 'Swift missing: install Xcode Command Line Tools (xcode-select --install)' >&2; exit 1; }
command -v brew >/dev/null || { echo 'Homebrew missing: install from https://brew.sh' >&2; exit 1; }
if ! brew list --versions libusb >/dev/null 2>&1; then
  echo 'Installing USB library with Homebrew…'
  brew install libusb
fi
if [[ ! -x .venv/bin/python ]]; then
  ./setup_mac.sh
fi
.venv/bin/python -m pip install -q 'pyinstaller>=6,<7'
# PyInstaller collects Python interpreter, numpy, Pillow, OpenCV, and PyUSB.
# Homebrew libusb is explicitly bundled; PalmClix loads that bundled dylib.
LIBUSB="$(brew --prefix libusb)/lib/libusb-1.0.0.dylib"
[[ -f "$LIBUSB" ]] || { echo "Missing $LIBUSB" >&2; exit 1; }
LIBUSB="$(cd "$(dirname "$LIBUSB")" && pwd -P)/$(basename "$LIBUSB")"
echo '1/5 Building embedded USB/photo processing helper…'
.venv/bin/python -m PyInstaller --noconfirm --clean --onedir \
  --name palmclix_backend --contents-directory _internal \
  --paths "$ROOT" \
  --hidden-import decode_palmclix \
  --add-binary "$LIBUSB:." \
  --distpath "$ROOT/.build-app-dist" \
  --workpath "$ROOT/.build-app-work" \
  --specpath "$ROOT/.build-app-work" \
  "$ROOT/palmclix.py"
HELPER="$ROOT/.build-app-dist/palmclix_backend/palmclix_backend"
[[ -x "$HELPER" ]] || { echo 'PyInstaller helper missing.' >&2; exit 1; }
echo '2/5 Testing bundled helper against BOTH recorded camera states…'
SMOKE="$(mktemp -d "${TMPDIR:-/tmp/}/palmclix-offline.XXXXXX")"
trap 'rm -rf "$SMOKE"' EXIT
if [[ -f "$ROOT/reference_capture.pcap" && -f "$ROOT/tests/fixtures/seven_photo_capture.pcap" ]]; then
  "$HELPER" --simulate "$ROOT/reference_capture.pcap" --format png --output "$SMOKE/ten" > "$SMOKE/ten.log" 2>&1 || {
    cat "$SMOKE/ten.log"; echo '10-photo backend replay failed; not assembling app.' >&2; exit 1;
  }
  "$HELPER" --simulate "$ROOT/tests/fixtures/seven_photo_capture.pcap" --format both --output "$SMOKE/seven" > "$SMOKE/seven.log" 2>&1 || {
    cat "$SMOKE/seven.log"; echo '7-photo backend replay failed; not assembling app.' >&2; exit 1;
  }
  for check in 'ten 10 png' 'seven 7 png' 'seven 7 jpg'; do
    read -r folder count ext <<< "$check"
    raw=$(find "$SMOKE/$folder/Raw" -maxdepth 1 -type f -name 'PalmClix_*.pgm' | wc -l | tr -d ' ')
    images=$(find "$SMOKE/$folder/Photos" -maxdepth 1 -type f -name "PalmClix_*.$ext" | wc -l | tr -d ' ')
    [[ "$raw" == "$count" && "$images" == "$count" ]] || {
      echo "Incomplete $folder / $ext replay: raw=$raw photos=$images; app not assembled." >&2; exit 1;
    }
  done
  echo 'Both recordings decoded correctly with the packaged Python helper.'
else
  echo 'Private USB recordings not present; skipping offline replay smoke tests.'
fi
"$HELPER" --forensics "$ROOT/tests/fixtures/after_power_loss_catalog.bin" > "$SMOKE/recovery_report.json" || { echo 'Recovery catalog analyzer failed' >&2; exit 1; }
if [[ -f "$ROOT/tests/fixtures/seven_photo_capture.pcap" ]]; then
  "$HELPER" --simulate "$ROOT/tests/fixtures/seven_photo_capture.pcap" --format png --profile legacy --output "$SMOKE/legacy" > "$SMOKE/legacy.log" 2>&1 || { echo 'Legacy decoder replay failed' >&2; exit 1; }
fi

echo '3/5 Compiling native Swift/AppKit interface…'
swift build -c release --product PalmClixMac
BIN_DIR="$(swift build -c release --show-bin-path)"
EXE="$BIN_DIR/PalmClixMac"
[[ -x "$EXE" ]] || { echo 'Compiled Swift executable missing.' >&2; exit 1; }
# SwiftPM resource bundles are needed for Bundle.module in both source and .app.
BUNDLE="$(find "$BIN_DIR" -maxdepth 1 -type d -name '*PalmClix*.bundle' | head -1)"
[[ -d "$BUNDLE" ]] || { echo 'Swift resource bundle missing' >&2; exit 1; }
echo '4/5 Assembling self-contained macOS application…'
APP="$ROOT/PalmClix.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/BackendRuntime" "$APP/Contents/Resources/Demo"
cp "$EXE" "$APP/Contents/MacOS/PalmClixMac"
cp -R "$BUNDLE" "$APP/Contents/Resources/"
cp -R "$ROOT/.build-app-dist/palmclix_backend/." "$APP/Contents/Resources/BackendRuntime/"
[[ -f "$ROOT/reference_capture.pcap" ]] && cp "$ROOT/reference_capture.pcap" "$APP/Contents/Resources/Demo/reference_capture.pcap"
if command -v iconutil >/dev/null && [[ -f "$ROOT/Artwork/PalmClix_icon_1024.png" ]]; then
  ICON_SET="$SMOKE/PalmClix.iconset"
  mkdir -p "$ICON_SET"
  for size in 16 32 128 256 512; do
    sips -s format png -z "$size" "$size" "$ROOT/Artwork/PalmClix_icon_1024.png" --out "$ICON_SET/icon_${size}x${size}.png" >/dev/null
    retina=$((size * 2))
    sips -s format png -z "$retina" "$retina" "$ROOT/Artwork/PalmClix_icon_1024.png" --out "$ICON_SET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICON_SET" -o "$APP/Contents/Resources/PalmClix.icns"
fi
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>com.palmclix.revival</string>
  <key>CFBundleName</key><string>PalmClix</string>
  <key>CFBundleDisplayName</key><string>PalmClix</string>
  <key>CFBundleExecutable</key><string>PalmClixMac</string>
  <key>CFBundleIconFile</key><string>PalmClix.icns</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.1.0</string>
  <key>CFBundleVersion</key><string>1100</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.photography</string>
</dict></plist>
PLIST
chmod +x "$APP/Contents/MacOS/PalmClixMac" "$APP/Contents/Resources/BackendRuntime/palmclix_backend"
# Local ad-hoc signing avoids unsigned-bundle launch failures after moving.
# This is not Developer ID signing, notarization, or a security guarantee.
echo '5/5 Applying local ad-hoc signature…'
if command -v codesign >/dev/null; then
  codesign --force --deep --sign - --timestamp=none "$APP"
  codesign --verify --deep --verbose=1 "$APP"
fi
cat <<EOF

PALMCLIX APP CREATED SUCCESSFULLY:
  $APP

Double-click PalmClix.app, or run: open "$APP"
You can move PalmClix.app into /Applications without retaining this folder.
This is a local, ad-hoc-signed build, not an Apple-notarized distribution.
EOF
