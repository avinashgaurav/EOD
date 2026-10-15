# Requirements, permissions and privacy

- **Hide private projects** via an `exclude.txt` file (NDA / job-hunt work).

## Requirements & permissions

The two required pieces are free and most likely already on your Mac. The rest
just determines what shows up on the receipt:

| Integrate | Why | Permission to grant |
|---|---|---|
| **[Hammerspoon](https://www.hammerspoon.org/)** (required) | The free automation app that hosts and draws the widget. | **Accessibility**: System Settings → Privacy & Security → Accessibility → enable Hammerspoon (for dragging + the hotkey). |
| **`python3`** (required) | Runs `extract.py`, the parser behind the receipt. Check with `python3 --version`. | None. Looked up in `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`. |
| **Claude Code** / **Codex** | EOD reads their local JSONL transcripts (`~/.claude/projects`, `~/.codex`) for the WORK section. Use at least one. | None: it only **reads** files already on your Mac. |
| Browser history | Powers the WEB section (Chrome / Brave automatic). | Safari history may need **Full Disk Access** for the Hammerspoon process. |

**Local-first, no API keys, no telemetry.** EOD reads local files and writes a <!--claim:no-network-->
receipt to its own `cache/` folder. The one exception is the **optional AI-polish**
step: if your `claude` CLI is logged in, EOD asks it to rewrite the day into
crisper, manager-ready bullets, through your **existing CLI login** (no API key).
Missing CLI? It falls back to fully-offline cleanup.

<details>
<summary><b>Exactly what that one step sends, so you can decide for yourself.</b></summary>

Nothing else in EOD leaves your Mac. When AI-polish runs, it sends:

| Sent | Not sent |
|---|---|
| Session titles | Anything from a project in `exclude.txt` |
| Up to 8 prompts per session, 160 chars each | Personal browsing (job boards, shopping, social) | <!--claim:polish-sends-prompts-->
| Commit subjects and PR titles | Mail, chat and calendar hosts |
| Meeting titles | Attendee lists and the collaborators EOD detects (a name you typed into a prompt or meeting title still goes) | <!--claim:polish-no-third-party-names-->
| Document filenames and their folder | File contents, ever |
| Page titles from work browsing | Screen-time app data |

Two things worth knowing. Your prompts do go, and prompts sometimes contain
paths, hostnames or pasted snippets. And this is your own Claude account via
your own CLI login, not a third party.

The call itself is sealed off: EOD runs `claude -p` with no tools, none of your <!--claim:polish-cli-isolated-->
settings, hooks, MCP servers or CLAUDE.md, and without saving a session, so the
summary cannot touch your files and never shows up later as "work".

See it for yourself before trusting any of the above:

```sh
python3 extract.py --show-polish-payload      # prints the exact text, sends nothing
touch polish.off                              # never run this step again
```

</details>

