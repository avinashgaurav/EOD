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
receipt to its own `cache/` folder. There are two exceptions, both yours to switch
on. The first is the **optional AI-polish** step: if your `claude` CLI is logged
in, EOD asks it to rewrite the day into crisper, manager-ready bullets, through
your **existing CLI login** (no API key). Missing CLI? It falls back to
fully-offline cleanup. Want the polish without anything leaving the Mac? Create
`ollama.txt` and the same step runs on a local [Ollama](https://ollama.com) model
at `127.0.0.1:11434` instead (see [Configuration](configuration.md)).

The second is the **↗ Send** button, and it sends only when you press it. It <!--claim:send-only-on-press-->
exists only if you create a `send.txt` (see [Configuration](configuration.md)),
and the first press only arms it; the second posts. What goes is the same
bullets shown on the card's WORK section, to the Slack or Teams webhook or
Linear issue you listed, and nothing else: no screen time, no browsing,
nothing from the full bill. It posts the card as it is and never asks the
`claude` CLI for anything. Building and refreshing the receipt never sends.
Your webhook URLs and Linear key stay in that file; EOD never prints or logs
them.

<!--claim:share-image-no-prompts-->
**The share image** (the **⇪** on the receipt) is drawn on your Mac by the WebKit
that ships with macOS and lands in `cache/` and on your clipboard; nothing is
uploaded unless you post it, and making it never calls the AI-polish step. It
carries the highlights you already have (cached or hand-edited) and the day's
totals. Never prompts, session titles, project names, sites or app names.

<details>
<summary><b>Exactly what that one step sends, so you can decide for yourself.</b></summary>

Apart from the Send button above, nothing else in EOD leaves your Mac. When
AI-polish runs, it sends:

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
your own CLI login, not a third party. With `ollama.txt` the same text goes to
Ollama on your own Mac instead, so none of it leaves the machine.

The call itself is sealed off: EOD runs `claude -p` with no tools, none of your <!--claim:polish-cli-isolated-->
settings, hooks, MCP servers or CLAUDE.md, and without saving a session, so the
summary cannot touch your files and never shows up later as "work".
One exception: if an older `claude` CLI stops with "unknown option" on one of
these flags, EOD retries once with plain `claude -p --output-format text`, so
that one call runs without the isolation flags (CLAUDE.md stays off). The retry
is written to `polish-error.log`. Update the CLI to keep every call sealed off.

See it for yourself before trusting any of the above:

```sh
python3 extract.py --show-polish-payload      # prints the exact text and where it would go, sends nothing
touch polish.off                              # never run this step again
```

</details>

## Network requests the Mac app makes

- **Check for updates** (menu, only when you click it): one request to `api.github.com` for the latest release tag. Nothing about you or your day is sent.
- **Send** (only after you confirm the preview): your update to the Slack, Teams or Linear destinations you saved in the Keychain.
- **AI tidy-up** (only if you turned it on): through your own `claude` CLI login, or to Ollama on this Mac.
- **Usage counts** stay on your Mac; there is no server. The menu opens them in a window you can select and copy from, if you want to share them.
