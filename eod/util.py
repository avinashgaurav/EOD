"""Pure helpers: text, dates, paths, the noise filter. No IO, no config."""

import json, os, glob, sys, html, re, time, sqlite3, shutil, tempfile, subprocess, hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse


# ── noise filter ────────────────────────────────────────────────────────────
# Exact one-word / acknowledgement turns that carry no task signal.
ACK = {
    "continue", "continue]", "conitinue", "conitnue", "contiue", "cont",
    "keep going", "keep going.", "dont stop bro", "go ahead", "go on", "proceed",
    "yeah", "yea", "yes", "yep", "yup", "ya", "ok", "okay", "k", "kk",
    "cool", "nice", "great", "sure", "done", "good", "fine", "perfect",
    "stop", "stop here", "retry", "wait", "hmm", "hm", "no", "nope", "nah",
    "1", "2", "3", "12", "123", "1234", ".", "..", "...", "\\", "1234 ", "got it",
    "yeah", "yeah keep going", "lemme check", "let me know", "let me know when done",
    "what ra", "ask me the ques again", "now", "yeah do that", "do that",
    "yes lets do all the 8points", "yup its that one", "yeah its that one",
}


# Prefixes / contains that mark a non-authored or system-injected line.
DROP_PREFIX = (
    "<task-notification", "<command-name>", "<command-message>",
    "<local-command-stdout>", "<local-command-caveat", "<system-reminder>",
    "[image:", "[request interrupted", "caveat:", "base directory for this skill",
    "this session is being continued", "continue from where you left off",
    "detect my project's dev servers",
    # EOD's own automated polish/test calls — never surface these as "work"
    "eod-auto-summary",
    "you are writing a person's end-of-day", "you convert a software engineer's raw daily",
    "reply with only this json", "reply only {", "say hi as json",
)


DROP_CONTAINS = ("<task-id>", "<tool-use-id>")


def is_noise(t: str) -> bool:
    s = t.strip()
    if not s:
        return True
    low = s.lower()
    if low in ACK:
        return True
    if any(low.startswith(p) for p in DROP_PREFIX):
        return True
    if any(c in low for c in DROP_CONTAINS):
        return True
    # very short residue that isn't a real instruction
    if len(s) < 5 and not s.isdigit() is False:
        pass
    if len(s) < 4:
        return True
    return False


def human_text(o):
    """Return the human-typed text of a 'user' record, or None."""
    if o.get("type") != "user":
        return None
    c = (o.get("message") or {}).get("content")
    if isinstance(c, str):
        txt = c
    elif isinstance(c, list):
        parts = []
        for b in c:
            if isinstance(b, dict):
                if b.get("type") == "tool_result":
                    return None
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
        txt = "\n".join(parts) if parts else None
    else:
        return None
    if not txt:
        return None
    return None if is_noise(txt) else txt.strip()


# Claude Code encodes a project's full path as a folder name, replacing every
# non-alphanumeric char with "-". Strip the user's home prefix generically so this
# works for any username, e.g. /Users/bob -> "-Users-bob".
HOME_ENC = re.sub(r"[^A-Za-z0-9]", "-", os.path.expanduser("~"))


def _proj_key(enc):
    d = enc
    if d.startswith(HOME_ENC):
        d = d[len(HOME_ENC):]
    # fold agent git-worktree dirs back into their parent project
    d = re.split(r"--?claude-worktrees", d)[0]
    # prettify: drop common path noise, keep it readable
    d = d.replace("Downloads-", "").replace("Documents-", "")
    return d.strip("-") or "(root)"


def proj_name(path):
    return _proj_key(os.path.basename(os.path.dirname(path)))


def _cwd_key(cwd):
    """Project key from a real cwd path (Codex), matching Claude's encoded keys."""
    return _proj_key(re.sub(r"[^A-Za-z0-9]", "-", cwd or ""))


def local_date_of(ts):
    """ISO ts (UTC, ...Z) -> local 'YYYY-MM-DD' and 'HH:MM'."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
    except Exception:
        return None, None
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


# A transcript whose mtime predates the target day cannot hold a row for that day,
# because mtime only moves forward. Skipping those files whole means we stop
# re-reading the entire history on every run: once you have a few months of
# sessions that is the overwhelming majority of the corpus, and it grows weekly.
SCAN_MARGIN = 3600        # absorbs clock skew and coarse mtime, costs ~nothing


def _scan_floor(target):
    """Earliest mtime a file can have and still contain rows for `target`."""
    try:
        return time.mktime(time.strptime(target, "%Y-%m-%d")) - SCAN_MARGIN
    except Exception:
        return 0.0        # unparseable date -> fall back to scanning everything


def _predates(path, floor):
    if not floor:
        return False
    try:
        return os.path.getmtime(path) < floor
    except OSError:
        return False      # cannot stat -> let the reader try, same as before


def _day_window(target):
    """(start, end) epoch bounds of the local target day, or (None, None)."""
    try:
        s = time.mktime(time.strptime(target, "%Y-%m-%d"))
        return s, s + 86400
    except Exception:
        return None, None


def _written_during(path, start, end):
    """Was this file written *inside* the target day?

    Deliberately narrower than _predates. That one asks "could this file hold the
    day", which is also true of every file touched since; this asks "was this file
    actually written that day", which is the only version that means anything when
    you page back to an earlier date.
    """
    if start is None:
        return False
    try:
        return start <= os.path.getmtime(path) < end
    except OSError:
        return False


def _day_epoch(date):
    return time.mktime(time.strptime(date, "%Y-%m-%d"))   # local midnight, unix secs


def fmt_dur(s):
    s = int(s); h, m = s // 3600, (s % 3600) // 60
    if h: return f"{h}h {m:02d}m"
    if m: return f"{m}m"
    return "<1m"


# ── renderers ─────────────────────────────────────────────────────────────────
def oneline(s, n=160):
    return " ".join(str(s).split())[:n]


def pretty_date(d):
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%a, %b %-d %Y")
    except Exception:
        return d


# Make each work item read as a clear, past-tense accomplishment for a standup /
# manager update — the leading imperative verb is conjugated and the line is tidied.
PAST = {
    "check": "Checked", "fix": "Fixed", "add": "Added", "build": "Built", "create": "Created",
    "update": "Updated", "implement": "Implemented", "refactor": "Refactored",
    "investigate": "Investigated", "debug": "Debugged", "write": "Wrote", "setup": "Set up",
    "remove": "Removed", "delete": "Deleted", "rename": "Renamed", "review": "Reviewed",
    "analyze": "Analyzed", "analyse": "Analysed", "extract": "Extracted", "test": "Tested",
    "run": "Ran", "deploy": "Deployed", "configure": "Configured", "install": "Installed",
    "research": "Researched", "draft": "Drafted", "design": "Designed", "plan": "Planned",
    "merge": "Merged", "push": "Pushed", "pull": "Pulled", "generate": "Generated",
    "parse": "Parsed", "connect": "Connected", "enable": "Enabled", "disable": "Disabled",
    "move": "Moved", "copy": "Copied", "document": "Documented", "explore": "Explored",
    "validate": "Validated", "verify": "Verified", "optimize": "Optimized", "improve": "Improved",
    "prepare": "Prepared", "send": "Sent", "reply": "Replied", "respond": "Responded",
    "schedule": "Scheduled", "integrate": "Integrated", "audit": "Audited", "clean": "Cleaned",
    "sync": "Synced", "rebuild": "Rebuilt", "wire": "Wired", "handle": "Handled",
    "support": "Supported", "resolve": "Resolved", "scope": "Scoped", "define": "Defined",
    "compare": "Compared", "convert": "Converted", "format": "Formatted", "set": "Set",
    "rework": "Reworked", "redesign": "Redesigned", "ship": "Shipped", "land": "Landed",
}


# obvious term fixups (typos / casing) so a manager isn't reading garbled handles
TERM_FIX = {"aviashdotcom": "avinashdotcom", "Avinashdotcom": "avinashdotcom",
            "Anaysis": "Analysis", "anaysis": "analysis", "recomemdnations": "recommendations"}


def clean_title(t):
    t = " ".join(str(t).split())
    if not t:
        return t
    t = t.rstrip(" .;:,-")
    words = t.split(" ")
    w0 = words[0].lower().strip(",.:;")
    if w0 == "login":
        if len(words) > 1 and words[1].lower() == "to":
            words[0:2] = ["Logged", "into"]
        else:
            words[0] = "Logged in"
    elif w0 in PAST:
        words[0] = PAST[w0]
        if len(words) > 2 and words[1].lower() == "and":          # "Extract and analyze" → "Extracted and analyzed"
            w2 = words[2].lower().strip(",.:;")
            if w2 in PAST:
                words[2] = PAST[w2][0].lower() + PAST[w2][1:]
    else:
        words[0] = words[0][:1].upper() + words[0][1:]
    out = " ".join(words)
    for a, b in TERM_FIX.items():
        out = out.replace(a, b)
    return out


BRAND_CASE = {"zopnight": "ZopNight", "zopdev": "ZopDev", "zopday": "ZopDay",
              "zopcloud": "ZopCloud", "seo": "SEO", "geo": "GEO", "ui": "UI",
              "api": "API", "pr": "PR", "v2": "V2", "rec": "Recs"}


def pretty_project(pn):
    s = pn
    for pre in ("Desktop-", "Downloads-", "Documents-", "Personal-"):
        if s.startswith(pre):
            s = s[len(pre):]
    if not s or s == "Desktop":
        return "Desktop"
    s = re.sub(r"-{2,}", "-", s).replace("-", " ").strip()
    for a, b in TERM_FIX.items():
        s = s.replace(a, b)
    out = []
    for w in s.split():
        lw = w.lower()
        if lw in BRAND_CASE:
            out.append(BRAND_CASE[lw])
        elif w.islower():
            out.append(w[:1].upper() + w[1:])
        else:
            out.append(w)   # preserve already-mixed-case words (ZopNight, PR1906…)
    return " ".join(out)


def host_of(url):
    try:
        h = urlparse(url).netloc.lower()
        return h[4:] if h.startswith("www.") else (h or "?")
    except Exception:
        return "?"


# Personal / job-hunt / shopping / social — NEVER show on the receipt or feed to the summary.
PERSONAL_DOMAINS = {
    "linkedin.com", "ashbyhq.com", "jobs.ashbyhq.com", "indeed.com", "naukri.com",
    "glassdoor.com", "lever.co", "greenhouse.io", "wellfound.com", "angel.co",
    "instahyre.com", "cutshort.io", "hirist.com", "onconferences.com",
    "dinein.petpooja.com", "petpooja.com", "swiggy.com", "zomato.com", "blinkit.com",
    "amazon.in", "amazon.com", "flipkart.com", "myntra.com",
    "instagram.com", "facebook.com", "twitter.com", "x.com", "netflix.com", "youtube.com",
    "whatsapp.com", "web.whatsapp.com", "reddit.com",
}


def _is_personal(host):
    return any(host == d or host.endswith("." + d) for d in PERSONAL_DOMAINS)
