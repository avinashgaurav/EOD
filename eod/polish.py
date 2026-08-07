"""The optional AI step. The only part of EOD that leaves the machine."""

import json, os, re, time, subprocess, hashlib
from datetime import datetime

from .util import oneline, pretty_date
from .config import CACHE, _full_env, app_path


# ── AI polish (optional) ──────────────────────────────────────────────────────
# Rewrites the day's raw activity into crisp, specific, manager-ready bullets using
# the LOCAL `claude` CLI (the user's existing login — no API key). Cached per day by
# a content hash so Claude is only called when the work actually changed. If the CLI
# is missing / errors / times out, we silently fall back to the offline cleanup.
POLISH_SENTINEL = "EOD-AUTO-SUMMARY"   # marks EOD's own claude calls so we never read them back as "work"


POLISH_PROMPT = (
    POLISH_SENTINEL + " (automated task — ignore):\n"
    "You are writing a person's END-OF-DAY work update for their MANAGER.\n"
    "Input is the day's raw Claude Code activity grouped by project ('## name'); each "
    "session has an AI title ('- ...') and the person's real prompts ('> ...').\n\n"
    "Produce a SHORT, CURATED list of the genuinely important things they did — the kind "
    "of line a person actually sends their manager. Quality of selection matters most.\n\n"
    "INCLUDE only substantive work: features built, issues/bugs fixed, docs/decks/sheets/"
    "content created, analyses, things shipped, meetings & discussions, collaboration with "
    "named people, deliverables shared.\n"
    "EXCLUDE trivial mechanical steps that are NOT worth telling a manager — opening or "
    "locating a repo, reading/finding files, checking repo access, logging in, setup/config, "
    "navigating, asking for paths, 'analyzing' just to look. If a whole session was only "
    "this, DROP it entirely.\n"
    "MERGE many small related sessions into ONE themed line (e.g. all website work → one line).\n\n"
    "STYLE — match these real examples exactly (voice, tone, length):\n"
    "- Worked on the Content Engine issues and Email infra.\n"
    "- Discussed with Engg on new changes for Website.\n"
    "- Worked on ZopDay and ZopNight Product Brief and shared that with Team.\n"
    "- Worked on ZopNight Feature Comparison Excel and Customer Battle Card.\n"
    "- Worked with Aman on Cold email infra setup and discussion.\n"
    "- Worked with Design on website changes suggested by Talvinder.\n"
    "- Made Product note from Changelogs and sent to Himani for partner mail.\n"
    "- Reworked content for the new Website and product pages post review.\n"
    "- Meeting with Design to review recent website updates and list content needs.\n\n"
    "RULES:\n"
    "- Start lines like the examples: 'Worked on…', 'Discussed with…', 'Worked with <name> on…', "
    "'Made…', 'Reworked…', 'Meeting with…'.\n"
    "- Use real specifics from the prompts: issue/PR numbers (#253, #254), people names, "
    "document/deliverable/product names. Never invent details not in the input.\n"
    "- Also fold in work DOCUMENTS created (decks/docs/sheets) and genuinely work-relevant "
    "Google Docs/Sheets/Slides or research from the DOCS sections (e.g. 'Made the ZopNight "
    "battlecard deck', 'Worked on the High Value Items doc'). STRICTLY EXCLUDE anything "
    "personal — email, chat, job-hunting, shopping, food, social. Never put those in the update.\n"
    "- When the PEOPLE line names collaborators, attribute the relevant work naturally "
    "('Worked with <name> on…', 'Paired with <name> on…') — only where it genuinely fits.\n"
    "- One line each, ~5-16 words, plain professional English, no first-person 'I', no fluff, "
    "no emojis.\n"
    "- Order by importance (most important first).\n\n"
    "Return TWO things as a JSON OBJECT:\n"
    '1. "highlights": array of 4-9 short top-level lines — the manager update (as above).\n'
    '2. "detailed": array of groups, each {"area": "<short theme/area name>", '
    '"items": ["<clear specific bullet>", ...]} — a MORE GRANULAR breakdown (2-8 bullets per '
    "area) of everything meaningful that day. SAME readable voice and rules; more detail and "
    "specifics (issue/PR numbers, files, people, outcomes). Still NEVER dump raw prompts — "
    "rewrite into clear accomplishments. Skip trivia. Group by theme/area, most important first.\n\n"
    "Output ONLY the JSON object. No markdown, no commentary.\n"
    'Example: {"highlights": ["Worked on Content Engine issues #253 and #254 (PR #268)"], '
    '"detailed": [{"area": "Content Engine", "items": ["Fixed chapter-count logic in the ebook '
    'wizard (#253)", "Raised plan capacity and added 4-variant preview (#254)", "Resolved '
    'path-traversal review blocker and opened PR #268"]}]}'
)


# Comms surfaces — kept in WEB display but NOT fed to the manager summary.
POLISH_WEB_SKIP = {"mail.google.com", "chat.google.com", "calendar.google.com", "meet.google.com"}


def _claude_bin():
    for p in (os.path.expanduser("~/.local/bin/claude"),
              "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if os.path.exists(p):
            return p
    return None


def _extract_json_obj(s):
    i, j = s.find("{"), s.rfind("}")
    return s[i:j + 1] if i >= 0 and j > i else s


def _clean_detailed(raw):
    """Normalize the AI 'detailed' groups into [{area, items:[str]}]."""
    out = []
    for g in raw if isinstance(raw, list) else []:
        if not isinstance(g, dict):
            continue
        area = oneline(g.get("area", ""), 60)
        items = [oneline(x, 160) for x in g.get("items", []) if isinstance(x, str) and x.strip()]
        if area and items:
            out.append({"area": area, "items": items})
    return out


def _polish_input(data):
    """Compact, stable text of everything the curator should consider."""
    lines = []
    for p in data["projects"]:
        lines.append("## " + p["name"])
        for s in p["sessions"]:
            lines.append("- " + oneline(s["title"], 90))
            for pr in s["prompts"][:8]:
                lines.append("    > " + oneline(pr["text"], 160))
    if data.get("commits"):
        lines.append("## SHIPPED — git commits")
        for c in data["commits"]:
            lines.append(f"- [{c['repo']}] {c['subject']}")
    if data.get("prs"):
        lines.append("## SHIPPED — GitHub PRs")
        for p in data["prs"]:
            lines.append(f"- {p['repo']} PR #{p['number']} ({p['state']}): {p['title']}")
    if data.get("meetings"):
        lines.append("## MEETINGS — calendar")
        for m in data["meetings"]:
            # Attendee names are other people's data and they never agreed to this,
            # so the title goes and the names stay. They still show on the receipt,
            # which never leaves the machine.
            lines.append(f"- {m['time']} {m['title']}")
    if data.get("docs"):
        lines.append("## DOCUMENTS — files created/edited today")
        for d in data["docs"]:
            lines.append(f"- {d['name']} (in {d['folder']})")
    # data["people"] is deliberately omitted: same reason as meeting attendees.
    if data.get("web"):
        lines.append("## DOCS & RESEARCH VIEWED (include only genuinely work-relevant ones)")
        for d in data["web"][:15]:
            if d["host"] in POLISH_WEB_SKIP:
                continue
            for t in d["titles"][:2]:
                lines.append(f"- [{d['host']}] {t['title']}")
    return "\n".join(lines)


# eod.lua re-runs the engine every 10 minutes, all day, hidden or not. On an
# active day the work genuinely changes on most of those ticks, so the input hash
# misses and the CLI runs: a ~40s subprocess plus real tokens, six times an hour,
# to move a few bullets. This is the floor between automatic re-summaries. The
# Regenerate button passes force=True and ignores it.
POLISH_MIN_INTERVAL = 1800   # seconds


def _polished_recently(path):
    """True if the cached summary is younger than the debounce floor."""
    try:
        return (time.time() - os.path.getmtime(path)) < POLISH_MIN_INTERVAL
    except OSError:
        return False          # no cache yet, or unreadable -> let it polish


def _polish_log(msg):
    """Record why an AI-polish attempt fell back, so a silent no-summary day is diagnosable.
    Best-effort: never let logging break the receipt."""
    try:
        with open(os.path.join(CACHE, "polish-error.log"), "a") as f:
            f.write(datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S ") + oneline(msg, 600) + "\n")
    except Exception:
        pass


def polish(data, force=False):
    """Curate the day into a short manager-ready highlights list via the local claude CLI.
    Honours user edits (won't overwrite) unless force=True (the Regenerate button)."""
    if os.path.exists(app_path("polish.off")):
        return
    cb = _claude_bin()
    if not (data["projects"] or data.get("commits") or data.get("meetings")):
        return
    raw = _polish_input(data)
    key = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    cache_path = os.path.join(CACHE, "polish-" + data["date"] + ".json")

    cached = cached_detail = None
    try:
        with open(cache_path) as fh:
            c = json.load(fh)
        if isinstance(c.get("highlights"), list) and c["highlights"]:
            cached = c["highlights"]
            cached_detail = c.get("detailed")
            if c.get("edited") and not force:      # user hand-edited → keep, never auto-overwrite
                data["highlights"] = cached
                data["detailed"] = cached_detail
                data["edited"] = True
                return
            if c.get("key") == key and not force:  # work unchanged → reuse, no claude call
                data["highlights"] = cached
                data["detailed"] = cached_detail
                return
    except Exception:
        pass

    # Deliberately outside the try above: a failure here should surface, not be
    # swallowed by that bare except. The work HAS changed at this point, we are
    # only declining to re-summarise it quite so often.
    if cached and not force and _polished_recently(cache_path):
        data["highlights"] = cached
        data["detailed"] = cached_detail
        return

    if not cb:
        _polish_log("no claude CLI found (looked in ~/.local/bin, /opt/homebrew/bin, /usr/local/bin)")
        if cached:
            data["highlights"] = cached
            data["detailed"] = cached_detail
        return
    cwd = os.path.join(CACHE, ".polish")
    try:
        os.makedirs(cwd, exist_ok=True)
    except Exception:
        cwd = None
    try:
        r = subprocess.run([cb, "-p", "--output-format", "text"],
                           input=POLISH_PROMPT + "\n\n" + raw,
                           capture_output=True, text=True, timeout=150, cwd=cwd, env=_full_env())
        if r.returncode != 0:
            raise ValueError("claude exit %s: %s" % (r.returncode, (r.stderr or r.stdout or "").strip()))
        obj = json.loads(_extract_json_obj(r.stdout.strip()))
        highlights = [oneline(x, 140) for x in obj.get("highlights", []) if isinstance(x, str) and x.strip()]
        detailed = _clean_detailed(obj.get("detailed"))
        if not highlights:
            raise ValueError("no highlights in output: " + r.stdout.strip()[:300])
    except Exception as e:
        _polish_log("%s: %s" % (type(e).__name__, e))
        if cached:                          # failure → keep the LAST GOOD summary, never the raw fallback
            data["highlights"] = cached
            data["detailed"] = cached_detail
        return

    with open(cache_path, "w") as fh:
        json.dump({"key": key, "highlights": highlights, "detailed": detailed}, fh)
    data["highlights"] = highlights
    data["detailed"] = detailed


# ── weekly rollup + history ─────────────────────────────────────────────────────
WEEKLY_PROMPT = (
    "You are writing a WEEKLY work update for a manager from a person's DAILY updates "
    "(one block per day below, each a list of that day's accomplishments).\n\n"
    "Merge the week into a concise summary. Rules:\n"
    "- Group by theme/area, most important first; dedupe work repeated across days; show the "
    "outcome (e.g. 'shipped', 'merged') rather than day-by-day churn.\n"
    "- Same voice as the dailies: 'Worked on…', 'Shipped…', 'Discussed with…', 'Met with…'.\n"
    "- Keep specifics: issue/PR numbers, people, deliverables. Never invent.\n"
    "Return a JSON OBJECT: {\"highlights\": [4-8 top weekly lines], "
    '"detailed": [{"area":"<theme>","items":["<bullet>", ...]}]}. Output ONLY the JSON object.'
)


def polish_weekly(data, force=False):
    if os.path.exists(app_path("polish.off")):
        return
    cb = _claude_bin()
    if not data["days"]:
        return
    raw = "\n".join("## " + pretty_date(d) + "\n" + "\n".join("- " + h for h in hl)
                    for d, hl in data["days"])
    key = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    cache_path = os.path.join(CACHE, "weekly-" + data["week_start"] + ".json")
    try:
        with open(cache_path) as fh:
            c = json.load(fh)
        if c.get("edited") and not force:          # hand-edited weekly → keep
            data["highlights"] = c.get("highlights", [])
            data["detailed"] = c.get("detailed", [])
            data["edited"] = True
            return
        if c.get("key") == key and not force:
            data["highlights"] = c.get("highlights", [])
            data["detailed"] = c.get("detailed", [])
            return
    except Exception:
        pass
    if not cb:
        # fallback: flatten by day
        data["detailed"] = [{"area": pretty_date(d), "items": hl} for d, hl in data["days"]]
        data["highlights"] = [h for _, hl in data["days"] for h in hl][:8]
        return
    cwd = os.path.join(CACHE, ".polish")
    try:
        os.makedirs(cwd, exist_ok=True)
    except Exception:
        cwd = None
    try:
        r = subprocess.run([cb, "-p", "--output-format", "text"],
                           input=WEEKLY_PROMPT + "\n\n" + raw,
                           capture_output=True, text=True, timeout=150, cwd=cwd, env=_full_env())
        obj = json.loads(_extract_json_obj(r.stdout.strip()))
        hl = [oneline(x, 140) for x in obj.get("highlights", []) if isinstance(x, str) and x.strip()]
        det = _clean_detailed(obj.get("detailed"))
        if not hl:
            raise ValueError("empty")
    except Exception:
        data["detailed"] = [{"area": pretty_date(d), "items": h} for d, h in data["days"]]
        data["highlights"] = [x for _, h in data["days"] for x in h][:8]
        return
    with open(cache_path, "w") as fh:
        json.dump({"key": key, "highlights": hl, "detailed": det}, fh)
    data["highlights"] = hl
    data["detailed"] = det
