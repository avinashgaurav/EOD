# EOD polish test: does the AI stick to the facts?

This is the first test of the AI polish step (`eod/polish.py`). That step turns a day's raw activity into short highlights a manager can read, plus a longer breakdown. I ran the test on 2026-10-15. I then fixed the problems it found and ran it again the same day. The fix ships in the same PR (see "Before and after the fix").

For EOD, the command-line tool *is* what users really run: `polish()` calls `claude -p --output-format text`. The test script (`evals/harness/run.py`) calls the real `polish(data, force=True)`. So all of these run exactly as they do for users:

- the real `POLISH_PROMPT`
- the real code that builds what gets sent, `_polish_input`, which removes meeting attendees and people's names
- the real code that reads and tidies the answer: `_extract_json_obj`, `oneline`, `_clean_detailed`

Only two things are swapped out, and only for the test:

- **The cache.** `polish.CACHE` points to a temporary folder, so no real saved results are read or written.
- **The command-line tool.** `polish._claude_bin` points to `evals/harness/claude_wrapper.py`. This wrapper sends the same prompt through `claude -p` with the same settings `polish()` uses. It changes three things:
  - the output format, from text to JSON, only so it can log speed, usage and which model answered; it hands `polish()` the same answer text
  - one setting: `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, so no CLAUDE.md file loads (the real app now sets this too; it did not during either test run)
  - `--model`, only if `EVAL_MODEL` is set (it was not set in these runs)

  If `polish()` did not pass the flags that shut out the user's own setup (true in the first run), the wrapper adds `--tools ""`, `--strict-mcp-config`, `--setting-sources ""` and `--no-session-persistence`.

How the test differs from a user's machine:

- **First run only: the real app did not shut out the user's setup.** On a user's machine, tools, personal settings, hooks, MCP servers and CLAUDE.md all loaded. So the first run measured the prompt alone, not whatever a given user's setup adds. Since the fix, the real app passes the same flags, and the wrapper passes the app's settings straight through.
- **No `--system-prompt` or `--json-schema`.** The app uses neither. The whole prompt is sent as one message, and the JSON is pulled out of the text answer.
- **No `--model`.** `polish.py` does not pick a model, so the tool's default model answered.
- **No `--bare`.** That option needs `ANTHROPIC_API_KEY`, and this run used a subscription login instead.

## Dataset

The test uses 10 made-up work days, in the exact shape `eod/pipeline.py` builds: projects, sessions, prompts, commits, PRs, meetings with attendees, documents and web history. All people, projects, products and issue numbers are made up. `evals/datasets/days.json`.

For each day, I wrote down the correct answers before the test:

| What the answer must contain | Count |
|---|---|
| Real work items that must show up somewhere in the highlights or the breakdown (1 marked minor: a footer-link update) | 29 |
| Details that must be kept exactly: issue/PR numbers, figures, document and product names, and the names of people mentioned in prompts | 30 |
| Things that must not appear | Per day |

The things that must not appear:

- small busywork steps (finding a repo, checking access, logging in, finding a template)
- personal web browsing (shopping, a job posting, sports news, flights, groceries, a gift search)

## Scoring checklist and measures

**Automatic checks**, in `run.py`:

1. **Dropped items.** A work item that does not show up anywhere in the output.
2. **Facts kept.** The exact detail (a number or name) is found in the output.
3. **Busywork or personal content included.** Something on the "must not appear" list showed up.
4. **Made-up numbers.** Any figure or `#ref` in the output that was not in what the AI was sent.
5. **Made-up names.** A meeting attendee's name in the output. Attendee names are removed before sending, so the AI never saw them.
6. **Unknown words.** Words that were not in what the AI was sent, are not English (`/usr/share/dict/words`) and are not common tech terms. These are listed for a person to check.
7. **Length.** 4 to 9 highlights, as the prompt asks. This is for information only: stretching a 3-item day to 4 lines would mean making something up.

**Manual review** (I read all 10 outputs once, side by side with what the AI was sent). I looked for made-up tasks and overstated results that automatic checks cannot spot, such as "shipped" when nothing shows it shipped. No other AI graded the answers.

## Results (first run, before the fix)

| What was checked | Result |
|---|---|
| Runs that returned highlights | 10 / 10 |
| Work items kept (not dropped) | **29 / 29** |
| Facts kept | **30 / 30** |
| Made-up numbers or issue references | **0** |
| Made-up names (attendee names were never sent) | **0** |
| Unknown words that were really made up (5 flagged, all turned out fine) | 0 |
| Personal or busywork items included | **0 / 10 days** |
| Days that passed every automatic check | 10 / 10 |
| Days with an overstated result (manual check) | **2 / 10** |
| Days with only a small embellishment (manual check) | 3 / 10 |
| Days with no problems on manual review | 5 / 10 |
| Days with 4 to 9 highlights | 4 / 10. The other 6 days had 3 or fewer work items. |

## Misses, by type (first run)

1. **Overstated result (2 days).** Both say "shipped" when the input shows a commit but no PR, merge or release:
   - day02: "Worked on the Quillmark PDF export bug (#77) and shipped the fix." The breakdown line also says "shipped the fix".
   - day10: "Built and shipped the Brambleworks case study page ..." The breakdown line says it again.

   This is the one finding that would mislead a manager.
2. **Small embellishment (3 days).** These are small additions, but the input still does not back them up:
   - day01: "Worked with Meera on ... hero copy". The input only says Meera wants it shorter.
   - day03: "Growth team for weekly sync". The word "weekly" is not in the input.
   - day07: "sent draft to Lena for review". The input says to send it. It does not show that it was sent.
3. **Dropped items, lost facts, made-up numbers or names, personal browsing leaking in:** none.

## Before and after the fix

The fix (changes to the real app, in the same PR as these results):

- `POLISH_PROMPT` gets two new rules. First: only say shipped, merged, deployed, released, sent, shared or met when the input shows it (a commit alone is "fixed" or "committed"; being told to send something does not prove it was sent). Second: never add people, teams, meetings, recipients or words about how often something happens unless they are in the input. `WEEKLY_PROMPT` works from the daily highlights, which have already been checked. It gets the "add nothing" rule plus a "do not upgrade" rule instead: keep shipped, merged, sent or met exactly as the daily line says it, and never turn 'worked on', 'fixed' or 'drafted' into 'shipped'. The weekly summary was not tested: this test covers the daily polish only.
- Both `claude -p` calls (daily and weekly) now pass `--tools ""`, `--strict-mcp-config`, `--setting-sources ""` and `--no-session-persistence`. A new README claim (`polish-cli-isolated`) and its test lock this in. The `POLISH_SENTINEL` filter stays. With `--no-session-persistence`, EOD's own calls are no longer saved to `~/.claude/projects`, so the filter should not be needed any more. But it costs little, works as a backup, and still covers old transcripts and older versions of the tool.
- Added after both runs: both calls also set `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` (checked against the text inside Claude Code 2.1.299, which skips loading CLAUDE.md when this is set). Also, if an older version of the tool stops with "unknown option" for one of the flags, the call is tried once more with the old `-p --output-format text`.

Tests after the fix: `./run_tests.sh` passes all 135 tests (133 before, plus the claim test and a test for the "unknown option" retry), including `test_claim_coverage`.

For the second run, the test wrapper passed `polish()`'s own settings straight through, changing only the output format. It also set `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, which the real app did not set yet. Same 10 days, same checks, same model. Results: `evals/results/2026-10-15-claude-cli.json` (before) and `evals/results/2026-10-15-claude-cli-after-fix.json` (after).

| What was checked | Before | After |
|---|---|---|
| Work items kept | 29 / 29 | 29 / 29 |
| Facts kept | 30 / 30 | 30 / 30 |
| Made-up numbers or names | 0 | 0 |
| Personal or busywork items included | 0 / 10 days | 0 / 10 days |
| **Days with an overstated result (manual check)** | **2 / 10** | **0 / 10** |
| **Days with only a small embellishment (manual check)** | **3 / 10** | **0 / 10** |
| Days with no problems on manual review | 5 / 10 | 10 / 10 |
| Days with 4 to 9 highlights | 4 / 10 | 3 / 10 (the other 7 days have 3 or fewer work items) |

Each earlier miss, checked again: day02 now says "Fixed ... (#77)" and "Committed the fix"; day10 says "Built and committed"; day01 says "per Meera's feedback"; day03 says "Growth sync"; day07 says "draft for Lena's review".

Misses left: none on these days. On small days, the number of highlights dropped further below the prompt's "4-9" minimum. That is the right choice when a day has only 2 or 3 items, but the prompt's minimum could be lowered to match. The same caution still applies: 10 hand-built days is a small sample. Going from 5/10 to 10/10 clean days is encouraging, not proof.

Speed on the second run: a typical call took 6.2 s (p50), a slow call took 8.6 s (p90), and the whole run took 22 s. Model: `claude-opus-5-5`.

## Speed and usage (first run)

- 10 calls: a typical call took 5.6 s (p50), a slow call took 6.5 s (p90), and the slowest took 6.5 s. The whole run took 22 s, with 3 calls running at once.
- The model that answered every call: `claude-opus-5-5`. It is the tool's default here, since `polish.py` does not pick one.
- Usage reported by the tool: about 41k tokens in and 2.8k tokens out.
- 0 errors from the tool.

## What the results mean

On these days, the AI kept every work item and every specific detail, and the privacy filters held. The first run led to one prompt fix and one code fix. Both are now in place (see above):

1. **Prompt fix (recommended).** Add a rule to `POLISH_PROMPT`:

   > "Only say shipped, merged, deployed or sent when the input shows it (a merged PR, or the person saying so). A commit alone is 'fixed' or 'committed'. Do not add collaborators, cadence words like 'weekly', or outcomes the input does not state."

   Run the 10 days again after the change.
2. **Code (worth considering).** `polish()` runs the tool without shutting out the user's setup, so a user's tools, hooks, MCP servers and CLAUDE.md all affect the summary. Adding these flags makes the output the same no matter how a user has set things up. It also removes the need to filter EOD's own sessions out using `POLISH_SENTINEL`:
   - `--tools ""`
   - `--strict-mcp-config`
   - `--setting-sources ""`
   - `--no-session-persistence`

   Choosing a fixed model with `--model` would also make results repeatable.

With fix 1 in and a clean second run, the numbers above are fair to publish, as long as it is clear this is 10 hand-built days.

## Reproduce

```sh
cd eod
python3 evals/harness/run.py                  # 10 CLI calls; writes evals/results/<date>-claude-cli.json
EVAL_TAG=after-fix python3 evals/harness/run.py   # same, written with an -after-fix suffix
EVAL_ONLY=day01,day02 python3 evals/harness/run.py   # subset; writes a -partial file
```

Requires Python 3.9+ and a logged-in `claude` CLI. No packages to install.
