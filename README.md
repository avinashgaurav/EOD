# EOD

> Your whole work day, printed as a receipt.

![platform: macOS](https://img.shields.io/badge/platform-macOS-black)
![runs on: Hammerspoon](https://img.shields.io/badge/runs%20on-Hammerspoon-3a86ff)
![license: MIT](https://img.shields.io/badge/license-MIT-green)

A tiny macOS desktop widget, styled as a **printed receipt**, that shows
**everything you got done that day** — your AI coding sessions, the sites and
docs you worked in, the commits you shipped — grouped and copy-paste ready for a
standup, timesheet, or task sheet. It rebuilds itself from files already on your
Mac. Local-first, no API keys (see [Requirements & permissions](#requirements--permissions)).

### Where it pulls from

| Source | Shows up as | Read from |
|---|---|---|
| **Claude Code** + **Codex** | **WORK** — your coding sessions, per project | their local JSONL transcripts |
| **Git** | shipped commits & PRs | repos in your work folders |
| **Documents** | decks / docs / sheets / PDFs you created or edited | your work folders |
| **Browsing** | **WEB** — the sites you spent time on | Chrome / Brave / Safari history |
| **Apps** | **SCREEN TIME** | local app-usage |

All local — nothing leaves your Mac (one optional exception, [below](#requirements--permissions)).

<p align="center">
  <img src="screenshots/brief.png" alt="EOD daily work receipt" width="220">
  &nbsp;&nbsp;
  <img src="screenshots/weekly.png" alt="EOD weekly recap" width="220">
</p>

<p align="center"><sub><b>Daily receipt</b> &nbsp;·&nbsp; <b>Weekly recap</b> &nbsp;—&nbsp; sample data; EOD builds these from your own activity, on your Mac.</sub></p>

Each line is the **work** done — the AI-generated session title from Claude Code
or Codex, a clean one-liner. No raw prompts.

<details>
<summary>Prefer text? Here's what the receipt looks like.</summary>

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

</details>

## Features

- **Auto-built daily** from your local activity — rolls over at midnight, refreshes through the day.
- **Multi-source** — Claude Code + Codex sessions, git commits, documents, browsing, and screen time on one receipt.
- **Daily receipt + weekly recap** — one keystroke from the menu bar.
- **Copy all** or per-project **copy**, straight to the clipboard.
- **◀ ▶ browse previous days** for back-filling a sheet.
- **Frameless + transparent** — only the cream paper shows on your wallpaper; drag it by the masthead. Floats over full-screen apps.
- **Prints down** when opened, **rolls up** when closed.
- **Hide private projects** via an `exclude.txt` file (NDA / job-hunt work).

## Requirements & permissions

The two required pieces are free and most likely already on your Mac. The rest
just determines what shows up on the receipt:

| Integrate | Why | Permission to grant |
|---|---|---|
| **[Hammerspoon](https://www.hammerspoon.org/)** (required) | The free automation app that hosts and draws the widget. | **Accessibility** — System Settings → Privacy & Security → Accessibility → enable Hammerspoon (for dragging + the hotkey). |
| **`python3`** (required) | Runs `extract.py`, the parser behind the receipt. Check with `python3 --version`. | None. Looked up in `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`. |
| **Claude Code** / **Codex** | EOD reads their local JSONL transcripts (`~/.claude/projects`, `~/.codex`) for the WORK section. Use at least one. | None — it only **reads** files already on your Mac. |
| Browser history | Powers the WEB section (Chrome / Brave automatic). | Safari history may need **Full Disk Access** for the Hammerspoon process. |

**Local-first, no API keys, no telemetry.** EOD reads local files and writes a
receipt to its own `cache/` folder. The one exception is the **optional AI-polish**
step: if your `claude` CLI is logged in, EOD asks it to rewrite the day into
crisper, manager-ready bullets — that goes through your **existing CLI login**
(no API key). Missing CLI? It silently falls back to fully-offline cleanup.

## Install

~3 minutes. Full guide in **[INSTALL.md](INSTALL.md)** — short version:

```sh
# don't already use Hammerspoon? drop EOD straight into its config:
mkdir -p ~/.hammerspoon && cp -R ./* ~/.hammerspoon/
```

Then open Hammerspoon → **Reload Config** (⌥⌃⌘R). The receipt prints down in the
top-right. (Already have an `init.lua`? Don't overwrite it — see INSTALL.md.)

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

## How it works

- **`extract.py`** parses every Claude Code and Codex `*.jsonl` transcript for the
  target day, takes each session's AI title, de-dupes per project, folds in git
  commits / documents / browser history / app usage, filters noise, and writes a
  self-contained receipt HTML to `cache/`.
- **`eod.lua`** is a Hammerspoon module that renders that HTML in a frameless
  `hs.webview`, runs the engine on a timer, and handles copy / nav / drag / animation.

---

MIT licensed.
