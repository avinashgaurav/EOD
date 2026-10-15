# Using EOD

For EOD the Claude Code CLI is the production path, so these runs used the real call through the real `polish()`. The eval wrapper changes only what it needs to record the run: JSON output instead of text (for latency, usage and model), and `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` in the environment, which production now sets too. The weekly rollup was not measured.

## Features

- **Auto-built daily** from your local activity; rolls over at midnight, refreshes through the day.
- **Multi-source**: Claude Code + Codex sessions, git commits, documents, browsing, and screen time on one receipt.
- **Daily receipt + weekly recap**: one keystroke from the menu bar.
- **Copy all** or per-project **copy**, straight to the clipboard.
- **Edit inline**: fix a line, **＋ add** one, or **✕ delete** one before you copy. On the **weekly recap** your hand-edits stick and survive a re-summarize (unless you force one with **⟳**).
- **◀ ▶ browse previous days** for back-filling a sheet.
- **Frameless + transparent**: only the cream paper shows on your wallpaper; drag it by the masthead. Floats over full-screen apps.

## Controls

| Action | How |
|---|---|
| Show / hide | menu-bar **▤**, or **⌥⌃⌘W** |
| Hide | the **✕** on the receipt |
| Move it | drag the **EOD** masthead |
| Copy the day | **⎙ Copy all** |
| Copy one project | the **⧉** on that project |
| Edit lines | **✎** on the WORK / weekly header, then **💾** to save |
| Add a line | **＋** on the WORK / weekly header |
| Delete a line | the **✕** beside a line (while editing) |
| Re-summarize | **⟳** (on the weekly recap this re-polishes, discarding hand-edits) |
| Previous / next day | **◀ ▶** |
| Refresh | **↻** |

## Command line

The receipt without the widget, for piping into a standup bot, a timesheet or a
cron job.

```sh
bin/eod today              # today's receipt as text
bin/eod today --md         # markdown, for a PR description or doc
bin/eod today --json       # the whole day
bin/eod day 2026-08-01     # any past day
bin/eod week               # the weekly recap
bin/eod sources            # what is set up on this machine, and what is not
bin/eod payload            # what AI-polish would send, without sending it
```

`--raw` skips the AI-polish step even when it is configured.
