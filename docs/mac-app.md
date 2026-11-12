# The Mac app

EOD ships as a native menu-bar app: no Hammerspoon and no Accessibility permission. It runs the same Python engine and shows the same receipt.

## Install

```sh
curl -fsSL https://eodreceipt.vercel.app/install.sh | bash
```

The script is short; read it first: [site/install.sh](../site/install.sh). It checks for macOS 13+ and python3, downloads `EOD.zip` from the latest GitHub release, puts `EOD.app` in Applications and opens it. No sudo, nothing else installed.

The app is not signed with an Apple Developer ID yet. Installed with the command above it opens normally. If you download `EOD.zip` in a browser instead, macOS blocks the first open: go to System Settings, Privacy & Security, and click **Open Anyway**.

## What changes from the Hammerspoon version

| | Hammerspoon | Mac app |
|---|---|---|
| Data folder (config files, cache) | `~/.hammerspoon/` | `~/Library/Application Support/EOD/` |
| Hotkey | ⌥⌃⌘W | ⌥⌃⌘W (no Accessibility needed) |
| Screen time | sampled every 15 s | same, same file format |
| Open at login | Hammerspoon's setting | **Open at login** in the menu, off until you turn it on |
| Shows in screen shares | yes | no: the receipt is hidden from Zoom, Meet and recordings |
| AI polish | on whenever `claude` is logged in | asked on first run, off unless you tick it (writes `polish.off`) |

Running both at once is not supported: they share the hotkey. To switch, remove the EOD lines from `~/.hammerspoon/init.lua`. To bring your settings across, copy `exclude.txt`, `repos.txt`, `send.txt`, `signature.txt` and `ollama.txt` into the app's data folder.

Uninstall: quit EOD from its menu, then `rm -rf /Applications/EOD.app ~/Library/Application\ Support/EOD`.

## Build it yourself

Needs only the Command Line Tools (`xcode-select --install`), not Xcode.

```sh
macos/build.sh          # macos/build/EOD.app (Apple silicon + Intel) and EOD.zip
```

Releases: push a tag like `v1.0.0` and `.github/workflows/release.yml` runs the tests, builds the app on a Mac runner and attaches `EOD.zip` to the release.
