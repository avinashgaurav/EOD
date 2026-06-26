# EOD

> Your day in Claude Code, printed as a receipt.

![platform: macOS](https://img.shields.io/badge/platform-macOS-black)
![runs on: Hammerspoon](https://img.shields.io/badge/runs%20on-Hammerspoon-3a86ff)
![license: MIT](https://img.shields.io/badge/license-MIT-green)

A macOS desktop widget — styled as a **printed bill/receipt** — that shows
**everything you did in Claude Code on a given day**, grouped by project and
copy-paste ready for a task sheet / standup / timesheet. It rebuilds itself from
the session transcripts under `~/.claude/projects` — fully local, no network, no API.

```
        ✂ ‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾
                 E O D
            DAILY WORK RECEIPT
        ────────────────────────
        DATE ......... Wed, Jun 24 2026
        ◀ PREV  NEXT ▶  ↻
        ════════════════════════
        EOD ................. ×2
          • Build the daily EOD widget       09:12
          • Add the print/roll animation     15:30
        GIT-CITY ............ ×1
          • Repo → 3D city skyline           11:55
        ────────────────────────
        PROJECTS ............ 2
        WORK ITEMS .......... 3
        ════════════════════════
             *** END OF DAY ***
            ▌▏▌▎▌▌▏▎▌▏▌▎▌
              [ ⎙ COPY ALL ]
        ✂ ____________________
```

Each line is the **work** done — Claude Code's own AI-generated session title, a
clean one-line summary. No raw prompts.

## Features

- **Auto-built daily** from `~/.claude` — rolls over to the new day at midnight,
  refreshes through the day.
- **Copy all** or per-project **copy** straight to the clipboard.
- **◀ ▶** browse previous days (for back-filling a sheet).
- **Frameless + transparent** — only the cream paper shows on your wallpaper;
  drag it by the masthead. Floats over full-screen apps too.
- **Prints down** when you open it, **rolls up** when you close it.
- **Hide private projects** via an `exclude.txt` file (NDA / job-hunt work).

## Requirements & permissions

You need three things, all free and most likely already on your Mac:

| Integrate | Why | Permission to grant |
|---|---|---|
| **Claude Code** | EOD reads your local session transcripts in `~/.claude/projects` to build the receipt. You must actually use Claude Code. | None — it only **reads** files already on your Mac. |
| **[Hammerspoon](https://www.hammerspoon.org/)** | The free automation app that hosts and draws the widget. | **Accessibility** — System Settings → Privacy & Security → Accessibility → enable Hammerspoon. Needed for dragging the receipt and the global hotkey. |
| **`python3`** | Runs `extract.py`, the parser that turns transcripts into the receipt. Check with `python3 --version`. | None. Looked up in `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`. |

**Local-first, no API keys, no telemetry.** EOD reads local files and writes a
receipt to its own `cache/` folder. The one exception is the **optional AI-polish**
step: if your `claude` CLI is logged in, EOD asks it to rewrite the day into
crisper, manager-ready bullets — that sends the day's activity to Claude through
**your existing CLI login** (no API key). If the CLI is missing it silently falls
back to fully-offline cleanup.

## Install

See **[INSTALL.md](INSTALL.md)**. Short version: needs
[Hammerspoon](https://www.hammerspoon.org/) + `python3` + Claude Code; drop this
folder in, point Hammerspoon at it, reload.

## How it works

- **`extract.py`** — parses every `*.jsonl` transcript for the target local day,
  takes each session's `aiTitle`, de-dupes per project, filters noise, and writes
  a self-contained receipt HTML to `cache/`.
- **`eod.lua`** — a Hammerspoon module that renders that HTML in a frameless
  `hs.webview`, runs the engine on a timer, handles copy/nav/drag, and animates.

## Controls

| Action | How |
|---|---|
| Show / hide | menu-bar **▤**, or **⌥⌃⌘W** |
| Hide | the **✕** on the receipt |
| Move it | drag the **EOD** masthead |
| Copy the day | **⎙ Copy all** |
| Copy one project | the **⧉** on that project |
| Previous / next day | **◀ ▶** |
| Refresh | **↻** |

MIT licensed.
