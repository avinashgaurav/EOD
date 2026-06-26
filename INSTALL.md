# Install — EOD

A little macOS desktop widget that turns your Claude Code activity into a daily
"work receipt." Takes ~3 minutes to set up.

## What you need

1. **Claude Code** — you must actually use it (the widget reads `~/.claude`).
2. **Hammerspoon** — the free automation app that hosts the widget.
   Download: <https://www.hammerspoon.org/> → drag to Applications → open it once
   → grant **Accessibility** when it asks (System Settings → Privacy & Security →
   Accessibility → enable Hammerspoon). This is needed for dragging + the hotkey.
3. **python3** — check in Terminal: `python3 --version`. If it's missing, macOS
   will offer to install the Command Line Tools, or run `brew install python`.

## Setup

### If you do NOT already use Hammerspoon (most people)

1. Copy this whole `EOD` folder into your Hammerspoon config folder so the
   files sit directly inside `~/.hammerspoon/`:
   ```sh
   mkdir -p ~/.hammerspoon
   cp -R /path/to/EOD/* ~/.hammerspoon/
   ```
   (After this you should have `~/.hammerspoon/init.lua`, `eod.lua`,
   `extract.py`.)
2. Open Hammerspoon → menu-bar hammer icon → **Reload Config** (or press
   ⌥⌃⌘R). The receipt prints down in the top-right.

### If you ALREADY have a Hammerspoon `init.lua`

Don't overwrite it. Put this folder anywhere (e.g. `~/EOD/`) and add these two
lines to your existing `~/.hammerspoon/init.lua`, fixing the path:

```lua
package.path = package.path .. ";" .. os.getenv("HOME") .. "/EOD/?.lua"
require("eod").start()
```

Then Reload Config.

## Using it

- **⌥⌃⌘W** or the menu-bar **▤** — show / hide the receipt
- Drag the **EOD** header to move it; **✕** to hide it
- **⎙ Copy all** copies the whole day; **⧉** copies one project
- **◀ ▶** browse other days; **↻** refresh

It starts automatically at login (Hammerspoon launches at login by default —
Hammerspoon Preferences → "Launch Hammerspoon at login").

## Hide private projects (optional)

To keep certain projects off the receipt (client / NDA / job-hunt work), copy
`exclude.txt.example` to `exclude.txt` and add one project name per line.

## Notes / troubleshooting

- **Nothing shows up?** Make sure Hammerspoon is running and you reloaded the
  config. Check the Hammerspoon Console (menu-bar icon → Console) for a line
  starting with `[eod]`.
- **"python not found"** — install python3 (see above); the widget looks in
  `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`.
- Everything stays on your machine. No data leaves your Mac.
