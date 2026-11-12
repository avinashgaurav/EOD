# Using EOD

For EOD the Claude Code CLI is the production path, so these runs used the real call through the real `polish()`. The eval wrapper changes only what it needs to record the run: JSON output instead of text (for latency, usage and model), and `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` in the environment, which production now sets too. The weekly rollup was not measured in those runs; it was first tested on 2026-11-04 (see [EVALS.md](../EVALS.md)).

## Features

- **Auto-built daily** from your local activity; rolls over at midnight, refreshes through the day.
- **Multi-source**: Claude Code + Codex sessions, git commits, documents, browsing, and screen time on one receipt.
- **Daily receipt + weekly recap**: one keystroke from the menu bar.
- **Weekly report**: the recap reads as a status report: key achievements, overall progress, challenges or blockers, time spent, collaboration, next steps, and tickets and PRs. Time spent and tickets are counted from your receipts, not written by the AI. Blockers, collaborators and next steps only appear when your daily updates show them; when the AI summary ran and found no blocker it says "None seen this week." **⎙ Copy report** copies the whole thing.
- **Copy all** or per-project **copy**, straight to the clipboard.
- **Share as an image**: **⇪** copies the day as a 16:9 PNG (2400×1350) for X or LinkedIn, with a small "made with EOD" footer. Highlights and totals only, no prompts.
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
| Share the day as an image | **⇪** (the PNG is on your clipboard and in `cache/<date>-share.png`) |
| Edit lines | **✎** on the WORK / weekly header, then **💾** to save |
| Add a line | **＋** on the WORK / weekly header |
| Delete a line | the **✕** beside a line (while editing) |
| Re-summarize | **⟳** (on the weekly recap this re-polishes, discarding hand-edits) |
| Previous / next day | **◀ ▶** |
| Refresh | **↻** |
| Post to Slack / Teams / Linear | **↗ Send**, twice (shown once you set up `send.txt`, see [Configuration](configuration.md)) |

## Command line

The receipt without the widget, for piping into a standup bot, a timesheet or a
cron job.

```sh
bin/eod today              # today's receipt as text
bin/eod today --md         # markdown, for a PR description or doc
bin/eod today --json       # the whole day
bin/eod day 2026-08-01     # any past day
bin/eod week               # the weekly recap
bin/eod timesheet          # time per project as CSV; prints the file's path
bin/eod sources            # what is set up on this machine, and what is not
bin/eod payload            # what AI-polish would send, without sending it
```

`--raw` skips the AI-polish step even when it is configured.

### Timesheet CSV

```sh
bin/eod timesheet                        # today -> cache/timesheet-YYYY-MM-DD.csv
bin/eod timesheet --date 2026-08-01      # any past day
bin/eod timesheet --week                 # Monday to today -> cache/timesheet-week-<Monday>.csv
bin/eod timesheet --week --out ~/ts.csv  # write it somewhere else
```

Columns: `date, project, source, start, end, minutes, sessions`. One row per
project per source (`claude` or `codex`) per day, sorted by date, then project,
then source. A day with no sessions writes the header row only. Projects whose
display names come out the same are merged into one row. A malformed or future
`--date` is refused (exit 2) and nothing is written.

How `minutes` is counted, so you can check it against the receipt:

- Each session counts from its first prompt to its last distinct prompt. Idle
  time in between is counted; time after the last prompt is not. Repeated
  prompts and filler such as "continue" are dropped before this, so a trailing
  "continue" adds nothing.
- A session with a single prompt counts as 0 minutes.
- Sessions that overlap are each counted in full, so a project's minutes can be
  more than the gap between its `start` and `end`.
- Times are local clock times, so a session that spans a daylight-saving change
  is off by up to 60 minutes.

`--week` reads every day from Monday up to `--date` (never past today) straight
from the Claude Code and Codex transcripts, rather than from old receipts in
`cache/`, so it is never stale. It runs only the session readers, not git,
browser history or the other sources. Rows stay per day; sum them in your
spreadsheet if you want weekly totals.

A project name starting with `=`, `+`, `-` or `@` gets a leading `'` so a
spreadsheet shows it as text instead of running it as a formula.
