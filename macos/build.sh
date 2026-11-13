#!/bin/bash
# Build EOD.app (universal: Apple silicon + Intel) without Xcode.
# Signing: with EOD_SIGN_P12 (base64 .p12) and EOD_SIGN_P12_PASSWORD set, it signs
# with that one long-lived certificate, so macOS keeps Keychain, Calendar and
# notification permissions across updates. Without them it signs ad-hoc.
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
    -framework AppKit -framework WebKit -framework ServiceManagement -framework UserNotifications -framework Carbon -framework Security -framework EventKit \
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
  <key>NSCalendarsUsageDescription</key><string>EOD reads today's meeting titles and times to put them on your receipt. Attendee names are never read.</string>
  <key>NSCalendarsFullAccessUsageDescription</key><string>EOD reads today's meeting titles and times to put them on your receipt. Attendee names are never read.</string>
  <key>NSHumanReadableCopyright</key><string>MIT licensed</string>
</dict></plist>
PLIST

cp Resources/EOD.icns Resources/MenuBarIconTemplate.png Resources/MenuBarIconTemplate@2x.png "$APP/Contents/Resources/"
# The engine, without caches or local config.
cp "$ROOT/extract.py" "$ROOT/exclude.txt.example" "$APP/Contents/Resources/engine/"
cp -R "$ROOT/eod" "$ROOT/bin" "$APP/Contents/Resources/engine/"
find "$APP/Contents/Resources/engine" -name '__pycache__' -type d -prune -exec rm -rf {} +

if { [ -n "${EOD_SIGN_P12:-}" ] && [ -z "${EOD_SIGN_P12_PASSWORD:-}" ]; } || { [ -z "${EOD_SIGN_P12:-}" ] && [ -n "${EOD_SIGN_P12_PASSWORD:-}" ]; }; then
  echo "set both EOD_SIGN_P12 and EOD_SIGN_P12_PASSWORD, or neither" >&2; exit 1
fi
if [ -n "${EOD_SIGN_P12:-}" ]; then
  # A throwaway keychain for this build only: the login keychain is never touched.
  # The cleanup is armed before anything secret reaches the disk.
  SIGNDIR="$(mktemp -d)"
  # codesign only finds identities in keychains on the search list, so the
  # throwaway one is added for the build and the original list put back after.
  OLD_KCS=()
  while IFS= read -r k; do k="${k#"${k%%[![:space:]]*}"}"; k="${k#\"}"; OLD_KCS+=("${k%\"}"); done < <(security list-keychains -d user)
  cleanup_sign() {
    [ ${#OLD_KCS[@]} -gt 0 ] && security list-keychains -d user -s "${OLD_KCS[@]}" >/dev/null 2>&1 || true
    security delete-keychain "$SIGNDIR/eod-sign.keychain-db" >/dev/null 2>&1 || true
    rm -rf "$SIGNDIR"
  }
  trap cleanup_sign EXIT
  KC="$SIGNDIR/eod-sign.keychain-db"; KCPW="$(openssl rand -hex 16)"
  P12="$SIGNDIR/eod.p12"; printf '%s' "$EOD_SIGN_P12" | base64 --decode > "$P12"
  security create-keychain -p "$KCPW" "$KC"
  security set-keychain-settings -lut 3600 "$KC"
  security unlock-keychain -p "$KCPW" "$KC"
  security list-keychains -d user -s "$KC" "${OLD_KCS[@]}"
  security import "$P12" -k "$KC" -f pkcs12 -P "$EOD_SIGN_P12_PASSWORD" -T /usr/bin/codesign >/dev/null
  security set-key-partition-list -S apple-tool:,apple: -s -k "$KCPW" "$KC" >/dev/null
  # The identity (certificate with its private key) usable for code signing.
  ID="$(security find-identity -p codesigning "$KC" | awk '/^ *1\)/{print $2; exit}')"
  [ -n "$ID" ] || { echo "signing certificate not found in the .p12" >&2; exit 1; }
  codesign --force --deep --keychain "$KC" --sign "$ID" "$APP"
  echo "signed with the EOD certificate ($ID)"
else
  codesign --force --deep --sign - "$APP"
  echo "signed ad-hoc (no EOD_SIGN_P12 set)"
fi
(cd "$OUT" && ditto -c -k --keepParent EOD.app EOD.zip)
echo "built $APP ($VERSION.$BUILD) and $OUT/EOD.zip"
