#!/bin/bash
# EOD installer. Read it before you run it:
#   curl -fsSL https://eodreceipt.vercel.app/install.sh | bash
#
# What it does, and nothing else:
#   1. checks this is macOS 13 or later with python3 available
#   2. downloads EOD.zip from the latest GitHub release (github.com/avinashgaurav/EOD)
#   3. puts EOD.app in /Applications (or ~/Applications if that is not writable)
#   4. opens it
# It needs no sudo, changes no settings and installs nothing else.
# Uninstall: quit EOD from its menu, then
#   rm -rf /Applications/EOD.app ~/Library/Application\ Support/EOD
set -euo pipefail

main() {

  REPO="avinashgaurav/EOD"
  URL="https://github.com/$REPO/releases/latest/download/EOD.zip"
  if [ -n "${EOD_VERSION:-}" ]; then URL="https://github.com/$REPO/releases/download/$EOD_VERSION/EOD.zip"; fi

  say() { printf '\033[1m%s\033[0m\n' "$*"; }
  die() { printf 'EOD install stopped: %s\n' "$*" >&2; exit 1; }

  [ "$(uname -s)" = "Darwin" ] || die "EOD runs on macOS only."
  major="$(sw_vers -productVersion | cut -d. -f1)"
  [ "$major" -ge 13 ] || die "EOD needs macOS 13 or later (this Mac has $(sw_vers -productVersion))."

  py=""
  for p in /opt/homebrew/bin/python3 /usr/local/bin/python3; do [ -x "$p" ] && py="$p" && break; done
  if [ -z "$py" ]; then
    if xcode-select -p >/dev/null 2>&1; then py=/usr/bin/python3
    else die "EOD needs python3. Run: xcode-select --install   (or: brew install python), then run this again."
    fi
  fi
  "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || die "EOD needs Python 3.9 or later ($py is older)."

  dest=/Applications
  [ -w "$dest" ] || { dest="$HOME/Applications"; mkdir -p "$dest"; }

  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  say "Downloading EOD…"
  curl -fsSL "$URL" -o "$tmp/EOD.zip" || die "could not download $URL"
  if curl -fsSL "$URL.sha256" -o "$tmp/EOD.zip.sha256" 2>/dev/null; then
    want="$(awk '{print $1}' "$tmp/EOD.zip.sha256")"
    got="$(shasum -a 256 "$tmp/EOD.zip" | awk '{print $1}')"
    [ "$want" = "$got" ] || die "checksum mismatch: the download is not the published EOD.zip"
    say "Checksum OK ($got)"
  fi
  ditto -x -k "$tmp/EOD.zip" "$tmp" || die "the download is not a valid zip"
  [ -d "$tmp/EOD.app" ] || die "the zip has no EOD.app inside"

  if pgrep -x EOD >/dev/null 2>&1; then
    say "Quitting the running EOD to update it…"
    osascript -e 'quit app "EOD"' >/dev/null 2>&1 || true
    for _ in $(seq 1 20); do pgrep -x EOD >/dev/null 2>&1 || break; sleep 0.5; done
    pgrep -x EOD >/dev/null 2>&1 && die "EOD is still running. Quit it from its menu-bar icon and run this again."
  fi
  rm -rf "$dest/EOD.app"
  ditto "$tmp/EOD.app" "$dest/EOD.app"

  if [ -f "$HOME/.hammerspoon/eod.lua" ]; then
    say "Note: you also have the Hammerspoon version of EOD."
    echo "Both use the ⌥⌃⌘W shortcut. To switch to the app, remove the EOD lines from ~/.hammerspoon/init.lua and reload Hammerspoon."
    echo "This installer did not change anything in ~/.hammerspoon."
  fi

  open "$dest/EOD.app"
  say "EOD is installed in $dest. Look for its icon in the menu bar, or press ⌥⌃⌘W."
}

main "$@"
