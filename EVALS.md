# EOD polish fidelity eval

First-pass eval of the AI polish step (`eod/polish.py`), which turns a day's raw activity into manager-ready highlights and a detailed breakdown. Run on 2026-10-15, then rerun the same day after the fix, which ships in the same PR (see "Before and after the fix").

For EOD the CLI *is* the production path: `polish()` shells out to `claude -p --output-format text`. The harness (`evals/harness/run.py`) calls the real `polish(data, force=True)`, so all of these run unchanged:

- the real `POLISH_PROMPT`
- the real payload builder `_polish_input`, which strips meeting attendees and people
- the real parsing and cleanup: `_extract_json_obj`, `oneline`, `_clean_detailed`

Only two things are redirected, both eval-only:

- **The cache.** `polish.CACHE` points to a temp dir, so no real cache is read or written.
- **The CLI binary.** `polish._claude_bin` points to `evals/harness/claude_wrapper.py`. The wrapper runs the same prompt through `claude -p` with `polish()`'s own argv, and changes three things:
  - the output format, text to JSON, only to log latency, usage and model; it hands `polish()` the same result text
  - the environment: `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, so no CLAUDE.md loads (production now sets this too; it did not during either run)
  - `--model`, only if `EVAL_MODEL` is set (it was not in these runs)

  If `polish()` did not pass the isolation flags (the first run), the wrapper adds `--tools ""`, `--strict-mcp-config`, `--setting-sources ""` and `--no-session-persistence`.

Differences from how it runs on a user's machine:

- **First run only: production had no isolation flags.** Tools, the user's settings, hooks, MCP servers and CLAUDE.md all loaded there, so the first run measured the prompt, not whatever a given user's setup adds. Since the fix, production passes the same flags, and the wrapper passes production's argv through.
- **No `--system-prompt` or `--json-schema`.** The app uses neither: the whole prompt is the user turn, and JSON is parsed from text.
- **No `--model`.** `polish.py` pins no model, so the CLI default answered.
- **No `--bare`.** It needs `ANTHROPIC_API_KEY`, and this run used a plan login.

## Dataset

10 fictional work days in the exact shape `eod/pipeline.py` builds: projects, sessions, prompts, commits, PRs, meetings with attendees, docs and web history. All people, projects, products and issue numbers are made up. `evals/datasets/days.json`.

Each day was written with its expected answers before the run:

| Expected answer | Count |
|---|---|
| Substantive work items that must survive somewhere in highlights or detailed (1 marked minor: a footer-link update) | 29 |
| Specifics that must be preserved: issue/PR numbers, figures, document and product names, collaborator names from prompts | 30 |
| Things that must not appear | Per day |

The things that must not appear:

- trivial steps (finding a repo, checking access, logging in, locating a template)
- personal web history (shopping, a job posting, sports news, flights, groceries, a gift search)

## Rubric and metrics

**Deterministic checks**, in `run.py`:

1. **Dropped items.** A work item with no marker match in the output.
2. **Facts preserved.** The fact regex is found in the output.
3. **Trivial or personal content included.** An exclude regex matched.
4. **Invented numbers.** Any figure or `#ref` in the output that is not in the payload the model saw.
5. **Invented names.** A meeting attendee name in the output. Attendees are stripped from the payload, so the model never saw them.
6. **Unknown tokens.** Words that are not in the payload, not English (`/usr/share/dict/words`) and not common tech terms. These are listed for manual review.
7. **Format.** 4 to 9 highlights, as the prompt asks. Informational only: padding a 3-item day to 4 lines would itself require invention.

**Manual review** (one read of all 10 outputs against the payload). It looked for invented tasks and overstated outcomes that regexes cannot see, such as "shipped" with no evidence of shipping. No LLM judge was used.

## Results (first run, before the fix)

| Metric | Result |
|---|---|
| Polish runs that returned highlights | 10 / 10 |
| Work items kept (not dropped) | **29 / 29** |
| Facts preserved | **30 / 30** |
| Invented numbers or issue refs | **0** |
| Invented names (attendees never sent) | **0** |
| Unknown tokens that were real inventions (5 flagged, all cleared) | 0 |
| Personal or trivial items included | **0 / 10 days** |
| Days passing every deterministic check | 10 / 10 |
| Days with an overstated outcome (manual) | **2 / 10** |
| Days with a minor embellishment only (manual) | 3 / 10 |
| Days fully clean on manual review | 5 / 10 |
| Highlights within 4 to 9 | 4 / 10. The other 6 days had 3 or fewer work items. |

## Misses, by failure category (first run)

1. **Overstated outcome (2 days).** Both are "shipped" claims where the input has a commit but no PR, merge or deploy:
   - day02: "Worked on the Quillmark PDF export bug (#77) and shipped the fix." The detail line also says "shipped the fix".
   - day10: "Built and shipped the Brambleworks case study page ..." The detail line repeats it.

   This is the one finding that would mislead a manager.
2. **Minor embellishment (3 days).** Small additions, but they are still words the input does not support:
   - day01: "Worked with Meera on ... hero copy". The input only says Meera wants it shorter.
   - day03: "Growth team for weekly sync". The word "weekly" is not in the input.
   - day07: "sent draft to Lena for review". The input is an instruction to send it, not a record that it was sent.
3. **Dropped items, lost facts, invented numbers or names, personal leakage:** none.

## Before and after the fix

The fix (production code, in the same PR as these results):

- `POLISH_PROMPT` gains two rules: only say shipped, merged, deployed, released, sent, shared or met when the input shows it (a commit alone is "fixed" or "committed"; an instruction to send is not proof it was sent), and never add people, teams, meetings, recipients or cadence words that are not in the input. The same two rules were added to `WEEKLY_PROMPT`, but the weekly rollup is unmeasured: this eval runs the daily polish only.
- Both `claude -p` calls (daily and weekly) now pass `--tools ""`, `--strict-mcp-config`, `--setting-sources ""` and `--no-session-persistence`. A new README claim (`polish-cli-isolated`) and its test pin this. The `POLISH_SENTINEL` filter is kept: with `--no-session-persistence` EOD's own calls are no longer written to `~/.claude/projects`, so the filter should no longer be needed, but it is a cheap second line of defence and still covers old transcripts and older CLI versions.
- Added after both runs: both calls also set `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` (checked against the strings in Claude Code 2.1.299, which skips CLAUDE.md loading when it is set), and if an older CLI exits with "unknown option" for one of the flags, the call is retried once with the old `-p --output-format text`.

Tests after the fix: `./run_tests.sh` passes, 135 tests (133 before, plus the claim test and a test for the unknown-option retry), including `test_claim_coverage`.

For the rerun, the eval wrapper passed `polish()`'s own argv through, changing only the output format, and set `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, which production did not yet set. Same 10 days, same checks, same model. Results: `evals/results/2026-10-15-claude-cli.json` (before) and `evals/results/2026-10-15-claude-cli-after-fix.json` (after).

| Metric | Before | After |
|---|---|---|
| Work items kept | 29 / 29 | 29 / 29 |
| Facts preserved | 30 / 30 | 30 / 30 |
| Invented numbers or names | 0 | 0 |
| Personal or trivial items included | 0 / 10 days | 0 / 10 days |
| **Days with an overstated outcome (manual)** | **2 / 10** | **0 / 10** |
| **Days with a minor embellishment only (manual)** | **3 / 10** | **0 / 10** |
| Days fully clean on manual review | 5 / 10 | 10 / 10 |
| Highlights within 4 to 9 | 4 / 10 | 3 / 10 (the other 7 days have 3 or fewer work items) |

Each earlier miss, rechecked: day02 now says "Fixed ... (#77)" and "Committed the fix"; day10 says "Built and committed"; day01 says "per Meera's feedback"; day03 says "Growth sync"; day07 says "draft for Lena's review".

Remaining misses: none on this set. The highlight count fell further below the prompt's "4-9" minimum on small days; that is the right call when a day has only 2 or 3 items, but the prompt's minimum could be relaxed to match. Caveat unchanged: 10 hand-built days is a small sample, so 5/10 to 10/10 clean is encouraging rather than conclusive.

Rerun latency: p50 6.2 s, p90 8.6 s, wall time 22 s. Model: `claude-opus-5-5`.

## Latency and usage (first run)

- 10 calls: p50 5.6 s, p90 6.5 s, max 6.5 s. Wall time 22 s at 3 concurrent.
- Model that answered every call: `claude-opus-5-5`, the CLI default here, since `polish.py` pins none.
- Usage reported by the CLI: about 41k input tokens and 2.8k output tokens.
- 0 CLI errors.

## Reading the result

Recall and specificity are strong on this set, and the privacy filters held. The first run recommended one prompt fix and one code fix; both are now applied (see above):

1. **Prompt fix (recommended).** Add a rule to `POLISH_PROMPT`:

   > "Only say shipped, merged, deployed or sent when the input shows it (a merged PR, or the person saying so). A commit alone is 'fixed' or 'committed'. Do not add collaborators, cadence words like 'weekly', or outcomes the input does not state."

   Rerun the 10 days after the change.
2. **Code (worth considering).** `polish()` runs the CLI with no isolation flags, so a user's tools, hooks, MCP servers and CLAUDE.md all apply to the summary. Adding these makes output independent of the user's setup and removes the need to filter EOD's own sessions out by `POLISH_SENTINEL`:
   - `--tools ""`
   - `--strict-mcp-config`
   - `--setting-sources ""`
   - `--no-session-persistence`

   Pinning `--model` would also make results reproducible.

With fix 1 in and a clean rerun, the numbers above are fair to publish with the caveat that this is 10 hand-built days.

## Reproduce

```sh
cd eod
python3 evals/harness/run.py                  # 10 CLI calls; writes evals/results/<date>-claude-cli.json
EVAL_TAG=after-fix python3 evals/harness/run.py   # same, written with an -after-fix suffix
EVAL_ONLY=day01,day02 python3 evals/harness/run.py   # subset; writes a -partial file
```

Requires Python 3.9+ and a logged-in `claude` CLI. No packages to install.
