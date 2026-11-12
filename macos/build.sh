#!/bin/bash
# Build EOD.app (universal: Apple silicon + Intel) without Xcode, ad-hoc signed.
#   macos/build.sh            -> macos/build/EOD.app and macos/build/EOD.zip
# Needs the Command Line Tools (swiftc). VERSION defaults to the latest git tag.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
VERSION="${VERSION:-$(git -C "$ROOT" describe --tags --abbrev=0 2>/dev/null | sed 's/^v//' || true)}"
VERSION="${VERSION:-0.1.0}"
[[ "$VERSION" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]] || { echo "VERSION must look like 1.2.3 (got '$VERSION')" >&2; exit 1; }
BUILD="$(git -C "$ROOT" rev-list --count HEAD 2>/dev/null || echo 1)"
OUT=build
APP="$OUT/EOD.app"
rm -rf "$OUT"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/engine"

for arch in arm64 x86_64; do
  swiftc -O -swift-version 5 -target "$arch-apple-macos13.0" \
    -framework AppKit -framework WebKit -framework ServiceManagement -framework UserNotifications -framework Carbon -framework Security \
    Sources/*.swift -o "$OUT/EOD-$arch"
done
lipo -create "$OUT/EOD-arm64" "$OUT/EOD-x86_64" -output "$APP/Contents/MacOS/EOD"
rm "$OUT"/EOD-arm64 "$OUT"/EOD-x86_64

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>EOD</string>
  <key>CFBundleDisplayName</key><string>EOD</string>
  <key>CFBundleIdentifier</key><string>com.avinashgaurav.eod</string>
  <key>CFBundleExecutable</key><string>EOD</string>
  <key>CFBundleIconFile</key><string>EOD</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION.$BUILD</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHumanReadableCopyright</key><string>MIT licensed</string>
</dict></plist>
PLIST

cp Resources/EOD.icns Resources/MenuBarIconTemplate.png Resources/MenuBarIconTemplate@2x.png "$APP/Contents/Resources/"
# The engine, without caches or local config.
cp "$ROOT/extract.py" "$ROOT/exclude.txt.example" "$APP/Contents/Resources/engine/"
cp -R "$ROOT/eod" "$ROOT/bin" "$APP/Contents/Resources/engine/"
find "$APP/Contents/Resources/engine" -name '__pycache__' -type d -prune -exec rm -rf {} +

codesign --force --deep --sign - "$APP"
(cd "$OUT" && ditto -c -k --keepParent EOD.app EOD.zip)
echo "built $APP ($VERSION.$BUILD) and $OUT/EOD.zip"
