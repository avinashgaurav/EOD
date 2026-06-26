#!/usr/bin/env python3
"""
avinash · EOD — engine.

Reads every Claude Code session transcript under ~/.claude/projects and rebuilds
"what I worked on" for one local calendar day. No network, no API — pure parse of
the JSONL transcripts Claude Code already writes.

For the target date it finds every session (file) that had real human activity
that day, and for each emits the session's AI-generated title plus the
substantive prompts (acks / tool-noise / pasted skill blobs filtered out),
grouped by project.

Writes three files into cache/:
  YYYY-MM-DD.json   structured  (consumed by eod.lua)
  YYYY-MM-DD.html   styled page (loaded into the desktop webview)
  YYYY-MM-DD.txt    plaintext   (debug / external tools)

Usage:  python3 extract.py [--date YYYY-MM-DD] [--print]
        (no --date  ->  today, local time)
"""
import json, os, glob, sys, html, re, time, sqlite3, shutil, tempfile, subprocess, hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

# Author's mark — printed on every receipt. Stored as char codes (not the literal
# text) so it doesn't turn up in a search, and re-inserted at render time if the
# footer line is ever edited out.
_SIG = "".join(map(chr, (65, 71)))

ROOT      = os.path.expanduser("~/.claude/projects")
CACHE     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")

# Projects to keep OFF the receipt (private / job-hunt / NDA) — one name per line in
# exclude.txt next to this script (lines starting with # are comments). Kept in a
# file, not the code, so private names never end up in the repo. Matches a project
# name exactly or any sub-folder of it.
def load_exclude():
    names = set()
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "exclude.txt")) as fh:
            for line in fh:
                s = line.strip()
                if s and not s.startswith("#"):
                    names.add(s)
    except FileNotFoundError:
        pass
    return names


EXCLUDE = load_exclude()


def is_excluded(pn):
    low = pn.lower()
    if "hammerspoon" in low and "polish" in low:   # EOD's own AI-polish scratch dir — never real work
        return True
    return any(pn == e or pn.startswith(e + "-") for e in EXCLUDE)

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


CODEX_ROOT = os.path.expanduser("~/.codex/sessions")


def add_codex(projects, target):
    """Merge OpenAI Codex sessions for `target` into the projects dict (same shape as Claude)."""
    for f in glob.glob(os.path.join(CODEX_ROOT, "*", "*", "*", "rollout-*.jsonl")):
        cwd, title, rows = None, None, []
        try:
            for line in open(f, errors="replace"):
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                p = o.get("payload") or {}
                if o.get("type") == "session_meta":
                    cwd = p.get("cwd") or (o.get("payload") or {}).get("cwd")
                    continue
                pt = p.get("type")
                if pt == "thread_name_updated" and p.get("thread_name"):
                    title = p["thread_name"]
                    continue
                if pt != "user_message":
                    continue
                ts = o.get("timestamp")
                if not ts:
                    continue
                day, hm = local_date_of(ts)
                if day != target:
                    continue
                msg = p.get("message")
                if not isinstance(msg, str):
                    continue
                if "<environment_context>" in msg or msg.lstrip().startswith("# Files mentioned by the user"):
                    # keep the actual ask in the "Files mentioned" wrapper, drop the env block
                    m = re.search(r"My request for Codex:\s*(.+)", msg, re.S)
                    msg = m.group(1) if m else ("" if "<environment_context>" in msg else msg)
                msg = oneline(msg, 200) if 'oneline' in globals() else " ".join(msg.split())[:200]
                if msg and not is_noise(msg):
                    rows.append((hm, msg))
        except Exception:
            continue
        if not rows:
            continue
        pn = _cwd_key(cwd) if cwd else "(root)"
        if is_excluded(pn):
            continue
        seen, prompts = set(), []
        for hm, txt in rows:
            k = txt[:64].lower()
            if k in seen:
                continue
            seen.add(k)
            prompts.append((hm, txt))
        if not title:
            title = prompts[0][1][:70]
        projects.setdefault(pn, []).append({
            "sid": "cx" + os.path.basename(f)[8:14],
            "title": title,
            "prompts": prompts,
            "start": prompts[0][0],
            "end": prompts[-1][0],
            "source": "codex",
        })


def build(target):
    # project -> session_id -> {title, file, prompts:[(hm,text)], start, end}
    projects = {}
    for f in glob.glob(os.path.join(ROOT, "*", "*.jsonl")):
        pn = proj_name(f)
        if is_excluded(pn):
            continue
        title = None
        rows = []  # (hm, text)
        try:
            for line in open(f, errors="replace"):
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                t = o.get("type")
                if t == "ai-title" and o.get("aiTitle"):
                    title = o["aiTitle"]
                    continue
                ts = o.get("timestamp")
                if not ts:
                    continue
                day, hm = local_date_of(ts)
                if day != target:
                    continue
                txt = human_text(o)
                if txt:
                    rows.append((hm, txt))
        except Exception:
            continue
        if not rows:
            continue
        # de-dup near-identical prompts within the session
        seen, prompts = set(), []
        for hm, txt in rows:
            key = txt[:64].lower()
            if key in seen:
                continue
            seen.add(key)
            prompts.append((hm, txt))
        sid = os.path.basename(f)[:8]
        if not title:
            title = prompts[0][1][:70]
        projects.setdefault(pn, []).append({
            "sid": sid,
            "title": title,
            "prompts": prompts,
            "start": prompts[0][0],
            "end": prompts[-1][0],
        })

    add_codex(projects, target)   # merge Codex sessions into the same project buckets

    # shape output, ordered by busiest project
    out_projects = []
    for pn, sessions in projects.items():
        sessions.sort(key=lambda s: s["start"])
        total = sum(len(s["prompts"]) for s in sessions)
        out_projects.append({
            "name": pretty_project(pn), "total": total,
            "sessions": [{
                "title": s["title"], "start": s["start"], "end": s["end"],
                "source": s.get("source", "claude"),
                "prompts": [{"t": t, "text": x} for t, x in s["prompts"]],
            } for s in sessions],
        })
    out_projects.sort(key=lambda p: -p["total"])
    commits = read_git(target)          # SHIPPED — local git commits
    meetings = read_meetings(target)    # MEETINGS — calendar (icalBuddy)
    return {
        "date": target,
        "generated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "projects": out_projects,
        "session_count": sum(len(p["sessions"]) for p in out_projects),
        "project_count": len(out_projects),
        "apps": read_usage(target),     # SCREEN TIME — written by eod.lua, today onward
        "web": read_web(target),        # WEB — parsed from local browser history
        "commits": commits,
        "prs": read_github(target),     # SHIPPED — GitHub PRs (gh active account)
        "meetings": meetings,
        "docs": read_docs(target),      # DOCUMENTS — files you created/edited (decks, docs, sheets)
        "people": collect_people(commits, meetings),  # collaborators
    }


# ── extra sources: app usage + browser history (all local) ─────────────────────
APP_MAX         = 30     # most apps to retain (full card lists all of these)
WEB_MAX_DOMAINS = 30     # most sites to retain (full card lists all of these)
WEB_TITLES_PER  = 6      # page titles retained per site (full card shows all)
APP_MIN_SECS    = 30     # ignore apps with less than this much active time
BRIEF_APPS      = 5      # apps shown on the FIRST (brief) card
BRIEF_WEB       = 6      # sites shown on the FIRST (brief) card (no per-page titles)

CHROME_EPOCH = 11644473600   # seconds from 1601-01-01 to the unix epoch
SAFARI_EPOCH = 978307200     # seconds from 2001-01-01 to the unix epoch


def fmt_dur(s):
    s = int(s); h, m = s // 3600, (s % 3600) // 60
    if h: return f"{h}h {m:02d}m"
    if m: return f"{m}m"
    return "<1m"


def read_usage(date):
    """App active-time for `date`, from cache/usage-YYYY-MM-DD.json (written live by Lua)."""
    p = os.path.join(CACHE, "usage-" + date + ".json")
    try:
        with open(p) as f:
            secs = json.load(f)
    except Exception:
        return []
    apps = [{"name": k, "secs": int(v)} for k, v in secs.items() if int(v) >= APP_MIN_SECS]
    apps.sort(key=lambda a: -a["secs"])
    return apps


def _day_epoch(date):
    return time.mktime(time.strptime(date, "%Y-%m-%d"))   # local midnight, unix secs


def _browser_dbs():
    home = os.path.expanduser("~")
    out = []
    for base in ("Library/Application Support/Google/Chrome",
                 "Library/Application Support/Google/Chrome Beta",
                 "Library/Application Support/BraveSoftware/Brave-Browser",
                 "Library/Application Support/Microsoft Edge",
                 "Library/Application Support/Arc/User Data",
                 "Library/Application Support/Chromium"):
        for h in glob.glob(os.path.join(home, base, "*", "History")):
            out.append(("chrome", h))
    saf = os.path.join(home, "Library/Safari/History.db")
    if os.path.exists(saf):
        out.append(("safari", saf))   # may be blocked by macOS unless Full Disk Access granted
    return out


def _query(path, sql, params):
    """Copy a (possibly locked, WAL-backed) sqlite db to temp and run one read query."""
    d = tempfile.mkdtemp(prefix="wl-")
    try:
        base = os.path.join(d, "h.db")
        shutil.copy2(path, base)
        for ext in ("-wal", "-shm"):
            if os.path.exists(path + ext):
                try: shutil.copy2(path + ext, base + ext)
                except Exception: pass
        con = sqlite3.connect(base)
        con.text_factory = lambda b: b.decode("utf-8", "replace")
        rows = con.execute(sql, params).fetchall()
        con.close()
        return rows
    finally:
        shutil.rmtree(d, ignore_errors=True)


def read_chrome(path, date):
    start = _day_epoch(date); end = start + 86400
    a = int((start + CHROME_EPOCH) * 1_000_000)
    b = int((end   + CHROME_EPOCH) * 1_000_000)
    sql = ("SELECT v.visit_time,u.url,u.title FROM visits v "
           "JOIN urls u ON u.id=v.url WHERE v.visit_time>=? AND v.visit_time<? "
           "ORDER BY v.visit_time")
    out = []
    try:
        for vt, url, title in _query(path, sql, (a, b)):
            unix = vt / 1_000_000 - CHROME_EPOCH
            out.append((datetime.fromtimestamp(unix).strftime("%H:%M"), url or "", title or ""))
    except Exception:
        pass
    return out


def read_safari(path, date):
    start = _day_epoch(date); end = start + 86400
    a = start - SAFARI_EPOCH; b = end - SAFARI_EPOCH
    sql = ("SELECT hv.visit_time,hi.url,hv.title FROM history_visits hv "
           "JOIN history_items hi ON hi.id=hv.history_item "
           "WHERE hv.visit_time>=? AND hv.visit_time<? ORDER BY hv.visit_time")
    out = []
    try:
        for vt, url, title in _query(path, sql, (a, b)):
            unix = vt + SAFARI_EPOCH
            out.append((datetime.fromtimestamp(unix).strftime("%H:%M"), url or "", title or ""))
    except Exception:
        pass
    return out


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
# Comms surfaces — kept in WEB display but NOT fed to the manager summary.
POLISH_WEB_SKIP = {"mail.google.com", "chat.google.com", "calendar.google.com", "meet.google.com"}


def _is_personal(host):
    return any(host == d or host.endswith("." + d) for d in PERSONAL_DOMAINS)


def read_web(date):
    """Browser visits for `date`, grouped by site (host), busiest first."""
    visits = []
    for kind, path in _browser_dbs():
        visits += read_chrome(path, date) if kind == "chrome" else read_safari(path, date)
    domains = {}
    for hm, url, title in visits:
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        h = host_of(url)
        if not h or h == "?" or _is_personal(h):
            continue
        d = domains.get(h)
        if not d:
            d = {"host": h, "count": 0, "titles": [], "_seen": set(), "start": hm, "end": hm}
            domains[h] = d
        d["count"] += 1
        if hm < d["start"]: d["start"] = hm
        if hm > d["end"]:   d["end"] = hm
        t = oneline(title, 70)
        if t and t.lower() not in d["_seen"]:
            d["_seen"].add(t.lower())
            d["titles"].append({"title": t, "t": hm})
    out = []
    for d in domains.values():
        d.pop("_seen", None)
        d["titles"] = d["titles"][:WEB_TITLES_PER]
        out.append(d)
    out.sort(key=lambda x: -x["count"])
    return out[:WEB_MAX_DOMAINS]


# ── git / github / calendar collectors (all local or your own gh/Calendar auth) ──
GIT_ROOTS = ["~/Desktop", "~/Documents", "~/code", "~/dev", "~/projects", "~/work", "~/repos"]


def _full_env():
    """Env that subprocesses (claude/gh/icalBuddy) need to authenticate — Hammerspoon's
    task env omits USER/PATH, which breaks auth."""
    try:
        import pwd
        u = pwd.getpwuid(os.getuid()).pw_name
    except Exception:
        u = os.path.basename(os.path.expanduser("~")) or "user"
    e = dict(os.environ)
    e["HOME"] = os.path.expanduser("~")
    e["USER"] = u
    e["LOGNAME"] = u
    e["PATH"] = ":".join([os.path.expanduser("~/.local/bin"), "/opt/homebrew/bin",
                          "/usr/local/bin", "/usr/bin", "/bin", e.get("PATH", "")])
    return e


def _git_repos():
    repos = set()
    cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "repos.txt")
    try:                                  # optional override/extra list, one path per line
        for line in open(cfg):
            s = line.strip()
            if s and not s.startswith("#") and os.path.isdir(os.path.join(os.path.expanduser(s), ".git")):
                repos.add(os.path.expanduser(s))
    except FileNotFoundError:
        pass
    for root in GIT_ROOTS:
        r = os.path.expanduser(root)
        if not os.path.isdir(r):
            continue
        try:
            out = subprocess.run(["find", r, "-maxdepth", "3", "-name", ".git"],
                                 capture_output=True, text=True, timeout=15).stdout
            for g in out.splitlines():
                repos.add(os.path.dirname(g))
        except Exception:
            continue
    return sorted(repos)


def read_git(date):
    """Your commits across local repos for `date` (filtered to your git identity)."""
    commits = []
    start, end = date + " 00:00:00", date + " 23:59:59"
    for repo in _git_repos():
        try:
            email = subprocess.run(["git", "-C", repo, "config", "user.email"],
                                   capture_output=True, text=True, timeout=5).stdout.strip()
            args = ["git", "-C", repo, "log", "--no-merges", "--since", start, "--until", end,
                    "--pretty=format:%h\t%s\t%(trailers:key=Co-authored-by,valueonly,separator=;)"]
            if email:
                args += ["--author", email]
            out = subprocess.run(args, capture_output=True, text=True, timeout=10).stdout
            name = os.path.basename(repo)
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                h, subj = parts[0], parts[1]
                co = parts[2] if len(parts) > 2 and not parts[2].startswith("%(") else ""
                coauthors = [re.sub(r"\s*<[^>]*>", "", x).strip() for x in co.split(";") if x.strip()]
                commits.append({"repo": name, "hash": h, "subject": oneline(subj, 100),
                                "coauthors": coauthors})
        except Exception:
            continue
    return commits


def read_github(date):
    """PRs you touched on `date`, via your gh CLI active account (best-effort)."""
    gh = next((p for p in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh") if os.path.exists(p)), None)
    if not gh:
        return []
    try:
        out = subprocess.run([gh, "search", "prs", "--author=@me", "--sort", "updated",
                              "--order", "desc", "--limit", "40", "--json",
                              "number,title,state,repository,createdAt,updatedAt,closedAt"],
                             capture_output=True, text=True, timeout=40, env=_full_env()).stdout
        prs = []
        for p in json.loads(out or "[]"):
            stamps = [p.get("createdAt", ""), p.get("updatedAt", ""), p.get("closedAt", "") or ""]
            if not any(str(s)[:10] == date for s in stamps):   # touched today (UTC ~ close enough)
                continue
            repo = (p.get("repository") or {}).get("name", "")
            prs.append({"number": p.get("number"), "title": oneline(p.get("title", ""), 100),
                        "state": p.get("state", ""), "repo": repo})
        return prs[:20]
    except Exception:
        return []


def _icalbuddy():
    return next((p for p in ("/opt/homebrew/bin/icalBuddy", "/usr/local/bin/icalBuddy")
                 if os.path.exists(p)), None)


def read_meetings(date):
    """Timed calendar events for `date` via icalBuddy (skips all-day items like holidays)."""
    ib = _icalbuddy()
    if not ib:
        return []
    try:
        out = subprocess.run([ib, "-nc", "-nrd", "-b", "@@@", "-eep", "notes,url,location",
                              "-iep", "title,datetime,attendees", "-tf", "%H:%M", "-df", "",
                              "eventsFrom:" + date, "to:" + date],
                             capture_output=True, text=True, timeout=20, env=_full_env()).stdout
    except Exception:
        return []
    meetings = []
    cur = None
    for line in out.splitlines():
        if line.startswith("@@@"):
            if cur and cur.get("time"):
                meetings.append(cur)
            cur = {"title": line[3:].strip(), "time": "", "attendees": ""}
        elif cur:
            s = line.strip()
            if re.match(r"^\d{1,2}:\d{2}", s):
                cur["time"] = s
            elif s.lower().startswith("attendees") or "@" in s:
                cur["attendees"] = (cur["attendees"] + " " + re.sub(r"^attendees:\s*", "", s, flags=re.I)).strip()
    if cur and cur.get("time"):
        meetings.append(cur)
    return meetings


_PEOPLE_SKIP = ("claude", "bot", "actions", "noreply", "dependabot", "github", "[bot]")


def collect_people(commits, meetings):
    """Collaborators from commit co-authors + meeting attendees (minus you and bots)."""
    try:
        me = subprocess.run(["git", "config", "--global", "user.name"],
                            capture_output=True, text=True, timeout=5).stdout.strip().lower()
    except Exception:
        me = ""
    names = {}
    def add(n):
        n = oneline(n, 40).strip(" ,")
        low = n.lower()
        if not n or "@" in n or any(s in low for s in _PEOPLE_SKIP):
            return
        if me and (low == me or low in me or me in low):
            return
        names.setdefault(low, n)
    for c in commits:
        for n in c.get("coauthors", []):
            add(n)
    for m in meetings:
        for n in re.split(r"[;,]", m.get("attendees", "")):
            add(n)
    return list(names.values())[:12]


DOC_ROOTS = ["~/Desktop", "~/Downloads", "~/Documents"]
DOC_EXTS = {"pptx", "ppt", "key", "docx", "doc", "pdf", "xlsx", "xls", "csv", "pages", "numbers"}
_DOC_SKIP_DIRS = {"node_modules", ".git", "Library", ".Trash", "cache", ".cache",
                  "venv", ".venv", "dist", "build", "__pycache__", ".next"}


def read_docs(date):
    """Documents you created/edited on `date` (decks, docs, sheets, PDFs) in your work folders."""
    out, seen = [], set()
    for root in DOC_ROOTS:
        base = os.path.expanduser(root)
        if not os.path.isdir(base):
            continue
        base_depth = base.rstrip("/").count("/")
        for dirpath, dirs, files in os.walk(base):
            if dirpath.rstrip("/").count("/") - base_depth >= 4:
                dirs[:] = []
            dirs[:] = [d for d in dirs if d not in _DOC_SKIP_DIRS and not d.startswith(".")]
            for f in files:
                ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
                if ext not in DOC_EXTS or f.startswith("~$") or f.startswith(".") or f in seen:
                    continue
                p = os.path.join(dirpath, f)
                try:
                    if datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d") != date:
                        continue
                except Exception:
                    continue
                seen.add(f)
                out.append({"name": f, "ext": ext, "folder": os.path.basename(dirpath)})
    return out[:40]


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
            lines.append(f"- {m['time']} {m['title']}" + (f" (with {m['attendees']})" if m.get("attendees") else ""))
    if data.get("docs"):
        lines.append("## DOCUMENTS — files created/edited today")
        for d in data["docs"]:
            lines.append(f"- {d['name']} (in {d['folder']})")
    if data.get("people"):
        lines.append("## PEOPLE you collaborated with today: " + ", ".join(data["people"]))
    if data.get("web"):
        lines.append("## DOCS & RESEARCH VIEWED (include only genuinely work-relevant ones)")
        for d in data["web"][:15]:
            if d["host"] in POLISH_WEB_SKIP:
                continue
            for t in d["titles"][:2]:
                lines.append(f"- [{d['host']}] {t['title']}")
    return "\n".join(lines)


def polish(data, force=False):
    """Curate the day into a short manager-ready highlights list via the local claude CLI.
    Honours user edits (won't overwrite) unless force=True (the Regenerate button)."""
    if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "polish.off")):
        return
    cb = _claude_bin()
    if not (data["projects"] or data.get("commits") or data.get("meetings")):
        return
    raw = _polish_input(data)
    key = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    cache_path = os.path.join(CACHE, "polish-" + data["date"] + ".json")

    cached = cached_detail = None
    try:
        c = json.load(open(cache_path))
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

    if not cb:
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
        obj = json.loads(_extract_json_obj(r.stdout.strip()))
        highlights = [oneline(x, 140) for x in obj.get("highlights", []) if isinstance(x, str) and x.strip()]
        detailed = _clean_detailed(obj.get("detailed"))
        if not highlights:
            raise ValueError("no highlights")
    except Exception:
        if cached:                          # failure → keep the LAST GOOD summary, never the raw fallback
            data["highlights"] = cached
            data["detailed"] = cached_detail
        return

    json.dump({"key": key, "highlights": highlights, "detailed": detailed}, open(cache_path, "w"))
    data["highlights"] = highlights
    data["detailed"] = detailed


def display_items(p):
    """Per-project fallback view (used when AI highlights aren't available)."""
    return [{"text": it["title"], "time": it["start"]} for it in items_of(p)]


def items_of(p):
    """The work done on a project = its session titles, de-duped, earliest first."""
    seen, order = {}, []
    for s in p["sessions"]:
        t = clean_title(oneline(s["title"], 90))
        if t not in seen:
            seen[t] = {"title": t, "start": s["start"]}
            order.append(t)
        else:
            seen[t]["start"] = min(seen[t]["start"], s["start"])
    return [seen[t] for t in order]


def time_window(data):
    starts = [s["start"] for p in data["projects"] for s in p["sessions"]]
    ends   = [s["end"]   for p in data["projects"] for s in p["sessions"]]
    for d in data.get("web", []):
        starts.append(d["start"]); ends.append(d["end"])
    return (min(starts) if starts else "--:--"), (max(ends) if ends else "--:--")


def work_item_count(data):
    if data.get("highlights"):
        return len(data["highlights"])
    return sum(len(display_items(p)) for p in data["projects"])


def highlights_text(data):
    return "\n".join("• " + h for h in data.get("highlights", []))


def to_text(data):
    """Brief, paste-when-asked summary: the important items, lightly grouped."""
    L = [f"Daily update — {pretty_date(data['date'])}", ""]
    if not (data["projects"] or data.get("apps") or data.get("web")):
        L.append("No activity recorded for this day.")
        return "\n".join(L)
    if data.get("highlights"):
        for h in data["highlights"]:
            L.append(f"  • {h}")
        L.append("")
    elif data["projects"]:
        for p in data["projects"]:
            L.append(p["name"])
            for it in display_items(p):
                L.append(f"  • {it['text']}")
        L.append("")
    if data.get("apps"):
        top = ", ".join(f"{a['name']} {fmt_dur(a['secs'])}" for a in data["apps"][:BRIEF_APPS])
        L.append("Screen time: " + top)
    if data.get("web"):
        sites = ", ".join(d["host"] for d in data["web"][:BRIEF_WEB])
        L.append("Browsed: " + sites)
    return "\n".join(L).rstrip() + "\n"


def to_text_full(data):
    """Everything, verbose: titles + the actual prompts, all apps, all sites + pages."""
    L = [f"Full work log — {pretty_date(data['date'])}", ""]
    if not (data["projects"] or data.get("apps") or data.get("web")
            or data.get("commits") or data.get("meetings")):
        L.append("No activity recorded for this day.")
        return "\n".join(L)
    if data.get("detailed"):
        L.append("WORK — DETAILED")
        for g in data["detailed"]:
            L.append("  " + g["area"])
            for it in g["items"]:
                L.append(f"    • {it}")
        L.append("")
    elif data["projects"]:
        L.append("CLAUDE CODE")
        for p in data["projects"]:
            L.append("  " + p["name"])
            for s in p["sessions"]:
                L.append(f"    • {clean_title(oneline(s['title'], 90))}  [{s['start']}–{s['end']}]")
                for pr in s["prompts"]:
                    L.append(f"        {pr['t']}  {oneline(pr['text'], 160)}")
        L.append("")
    if data.get("commits") or data.get("prs"):
        L.append("SHIPPED")
        for p in data.get("prs", []):
            L.append(f"  PR #{p['number']} ({p['state']}) — {p['title']}  [{p['repo']}]")
        byrepo = {}
        for c in data.get("commits", []):
            byrepo.setdefault(c["repo"], []).append(c)
        for repo, cs in byrepo.items():
            L.append("  " + repo)
            for c in cs:
                L.append(f"    • {c['subject']}")
        L.append("")
    if data.get("meetings"):
        L.append("MEETINGS")
        for m in data["meetings"]:
            L.append(f"  {m['time']}  {m['title']}" + (f"  ({m['attendees']})" if m.get("attendees") else ""))
        L.append("")
    if data.get("docs"):
        L.append("DOCUMENTS")
        for d in data["docs"]:
            L.append(f"  {d['name']}  ({d['folder']})")
        L.append("")
    if data.get("apps"):
        L.append("SCREEN TIME")
        for a in data["apps"][:APP_MAX]:
            L.append(f"  {a['name']} — {fmt_dur(a['secs'])}")
        L.append("")
    if data.get("web"):
        L.append("WEB")
        for d in data["web"]:
            L.append(f"  {d['host']} ×{d['count']}  [{d['start']}–{d['end']}]")
            for t in d["titles"]:
                L.append(f"    - {t['t']}  {t['title']}")
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def project_text(p):
    L = [p["name"]]
    for it in display_items(p):
        L.append(f"  • {it['text']}")
    return "\n".join(L)


def apps_text(data):
    L = ["SCREEN TIME"]
    for a in data.get("apps", [])[:APP_MAX]:
        L.append(f"  {a['name']} — {fmt_dur(a['secs'])}")
    return "\n".join(L)


def web_text(data):
    L = ["WEB"]
    for d in data.get("web", []):
        L.append(f"  {d['host']} ×{d['count']}")
        for t in d["titles"]:
            L.append(f"    - {t['title']}")
    return "\n".join(L)


CSS = """
:root{
  --surface:#14151a;          /* the dark desk the receipt sits on */
  --paper:#f3ecdd;            /* warm thermal paper */
  --ink:#2a2620;              /* warm near-black ink */
  --ink2:#9a8f7c;             /* faded ink */
  --line:#cdc2aa;             /* printed rule */
  --accent:#bf3d1f;           /* stamp red-orange */
  --mono:'SF Mono',ui-monospace,Menlo,'Courier New',monospace;
}
*{box-sizing:border-box}
html,body{margin:0}
body{background:transparent;font-family:var(--mono);-webkit-font-smoothing:antialiased}
/* transparent so only the paper shows on the desktop; padding leaves room for the shadow */
.surface{min-height:100vh;display:flex;justify-content:center;padding:16px 0 30px;background:transparent}
.grip{cursor:grab}
.grip:active{cursor:grabbing}
.hide{position:absolute;top:9px;right:11px;border:none!important;background:transparent!important;
  color:var(--ink2);font-size:13px;line-height:1;letter-spacing:0;padding:3px 5px}
.hide:hover{color:var(--accent)}

/* ── the paper ───────────────────────────────────────────────── */
.receipt{
  width:%W%px;background:var(--paper);color:var(--ink);
  padding:22px 22px 20px;position:relative;
  clip-path:%CLIP%;
  filter:drop-shadow(0 10px 22px rgba(0,0,0,.55));
  background-image:repeating-linear-gradient(0deg, rgba(0,0,0,.022) 0 1px, transparent 1px 3px);
  letter-spacing:.2px;
}
.receipt::after{ /* faint print fade / vignette */
  content:"";position:absolute;inset:0;pointer-events:none;clip-path:inherit;
  background:radial-gradient(120% 80% at 50% 50%, transparent 60%, rgba(120,100,60,.08));}

/* ── masthead ────────────────────────────────────────────────── */
.brand{text-align:center;font-size:20px;font-weight:700;letter-spacing:5px}
.brand b{color:var(--accent)}
.tag{text-align:center;font-size:9.5px;letter-spacing:3px;color:var(--ink2);margin-top:3px}
.stamp{display:block;width:max-content;margin:9px auto 2px;border:1.5px solid var(--accent);
  color:var(--accent);font-size:9px;letter-spacing:2px;padding:2px 8px;border-radius:3px;
  transform:rotate(-3deg);opacity:.9}

.rule{border-top:1px dashed var(--line);margin:11px 0}
.rule.solid{border-top:1.5px solid var(--ink)}
.rule.double{border-top:1.5px double var(--ink)}

/* key/value rows with dotted leaders */
.kv{display:flex;align-items:flex-end;font-size:11px;line-height:1.7}
.kv .k{color:var(--ink2);text-transform:uppercase;letter-spacing:1px;white-space:nowrap}
.kv .dots{flex:1;border-bottom:1px dotted var(--line);margin:0 5px 4px}
.kv .v{white-space:nowrap}
.kv.tot{font-size:11.5px}
.kv.tot .k{color:var(--ink)}
.kv.tot .v{font-weight:700}

/* nav row */
.nav{display:flex;gap:6px;justify-content:center;margin:10px 0 2px}
button{font-family:var(--mono);font-size:9.5px;letter-spacing:1.5px;text-transform:uppercase;
  color:var(--ink);background:transparent;border:1px dashed var(--line);border-radius:4px;
  padding:5px 9px;cursor:pointer;transition:.12s}
button:hover{border-color:var(--ink);background:rgba(0,0,0,.04)}

/* section label (CLAUDE CODE / SCREEN TIME / WEB) */
.sect{font-size:9.5px;letter-spacing:3px;color:var(--accent);text-transform:uppercase;
  font-weight:700;margin:4px 0 2px;text-align:center}

/* departments (= projects) */
.dept{margin:9px 0}
.depthead{display:flex;align-items:flex-end;font-weight:700;font-size:12px;
  text-transform:uppercase;letter-spacing:1px}
.depthead .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:215px}
.depthead .dots{flex:1;border-bottom:1px dotted var(--line);margin:0 6px 4px}
.depthead .qty{color:var(--ink2);font-weight:700;white-space:nowrap}
.depthead .cp{margin-left:7px;padding:1px 5px;font-size:9px;border-style:solid;opacity:.55}
.depthead .cp:hover{opacity:1}
.item{display:flex;gap:8px;font-size:11.5px;line-height:1.45;margin:3px 0 0 2px}
.item .t{flex:1}
.item .t b{color:var(--accent);font-weight:700;margin-right:5px}
.item .tm{color:var(--ink2);font-size:10px;white-space:nowrap;padding-top:1px}
.item.subt{margin-left:14px}
.item.subt .t{color:var(--ink2);font-size:10.5px}
.htext.editing{outline:1px dashed var(--accent);background:rgba(191,61,31,.06);
  border-radius:3px;padding:0 3px;margin-left:-3px}
.edot{color:var(--accent);font-size:9px;margin-left:4px}
.dim{color:var(--ink2);font-size:10px}
.dpick{font-family:var(--mono);font-size:9.5px;color:var(--ink);background:transparent;
  border:1px dashed var(--line);border-radius:4px;padding:4px 6px;cursor:pointer}
.dpick:hover{border-color:var(--ink)}

/* footer */
.end{text-align:center;font-size:11px;letter-spacing:3px;color:var(--ink);margin:6px 0 2px}
.barcode{height:46px;width:78%;margin:10px auto 4px;
  background-repeat:repeat-x;background-size:21px 100%;
  background-image:repeating-linear-gradient(90deg,
    var(--ink) 0 2px, transparent 2px 5px, var(--ink) 5px 6px, transparent 6px 11px,
    var(--ink) 11px 14px, transparent 14px 16px, var(--ink) 16px 17px, transparent 17px 21px);}
.bcnum{text-align:center;font-size:10px;letter-spacing:3px;color:var(--ink)}
.actions{display:flex;gap:7px;justify-content:center;margin:12px 0 4px}
.copyall{border-style:solid;border-color:var(--ink);font-weight:700;padding:7px 14px}
.copyall:hover{background:var(--ink);color:var(--paper)}
.copyall.seeall{border-style:dashed;border-color:var(--accent);color:var(--accent);font-weight:700}
.copyall.seeall:hover{background:var(--accent);color:var(--paper)}
.ts{text-align:center;font-size:9px;letter-spacing:1px;color:var(--ink2);margin-top:8px}
.sig{color:var(--ink);font-weight:700;letter-spacing:2px}
.empty{text-align:center;color:var(--ink2);font-size:11px;letter-spacing:2px;padding:34px 0}

.toast{position:fixed;left:50%;bottom:18px;transform:translateX(-50%) translateY(16px);
  background:var(--ink);color:var(--paper);font-size:10px;letter-spacing:2px;text-transform:uppercase;
  padding:8px 16px;border-radius:3px;opacity:0;transition:.22s;pointer-events:none}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}

/* ── print / unroll animation (paper fed from a slot at the top) ── */
.roll{transform-origin:top center}
html.anim-in  .roll{animation:printDown .85s cubic-bezier(.18,.86,.24,1) both}
html.anim-out .roll{animation:rollUp   .42s cubic-bezier(.45,0,.7,.25) both}
@keyframes printDown{
  0%{clip-path:inset(0 0 100% 0);transform:translateY(-4px)}
  100%{clip-path:inset(0 0 0 0);transform:translateY(0)}}
@keyframes rollUp{
  0%{clip-path:inset(0 0 0 0)}
  100%{clip-path:inset(0 0 100% 0);transform:translateY(-3px)}}
@media (prefers-reduced-motion:reduce){
  html.anim-in .roll,html.anim-out .roll{animation-duration:.001s}}
"""

JS = """
function send(m){try{window.webkit.messageHandlers.eod.postMessage(m);return true}catch(e){return false}}
function toast(t){var el=document.getElementById('toast');el.textContent=t;el.classList.add('show');
clearTimeout(window._tt);window._tt=setTimeout(function(){el.classList.remove('show')},1300)}
function copyText(txt,label){
  if(!send({action:'copy',text:txt})){ // browser fallback
    var ta=document.createElement('textarea');ta.value=txt;document.body.appendChild(ta);
    ta.select();try{document.execCommand('copy')}catch(e){}ta.remove();}
  toast((label||'Copied')+' ✓');}
function copyEl(id,label){copyText(document.getElementById(id).textContent,label)}
function nav(d){send({action:'nav',delta:d})}
function goDate(v){if(v)send({action:'goDate',date:v})}
function refresh(){send({action:'refresh'});toast('Refreshing…')}
function regen(){send({action:'regen'});toast('Re-summarizing…')}
function toggleEdit(){
  var list=document.getElementById('workList');var b=document.getElementById('editBtn');
  if(!list)return;var spans=list.querySelectorAll('.htext');
  if(list.getAttribute('data-edit')!=='1'){
    spans.forEach(function(s){s.contentEditable='true';s.classList.add('editing');});
    list.setAttribute('data-edit','1');if(b)b.textContent='💾';if(spans[0])spans[0].focus();
    toast('Edit — click 💾 to save');
  }else{
    var items=[];spans.forEach(function(s){var t=s.textContent.replace(/\\s+/g,' ').trim();if(t)items.push(t);
      s.contentEditable='false';s.classList.remove('editing');});
    list.setAttribute('data-edit','0');if(b)b.textContent='✎';
    send({action:'saveEdits',items:items});toast('Saved ✓');
  }
}
function drag(e){if(e.button===0)send({action:'dragStart'})}
window.playOut=function(){var h=document.documentElement;h.classList.remove('anim-in');h.classList.add('anim-out')};
"""


def clip_path(w=340, step=10, depth=6):
    """A torn-paper silhouette: zigzag top & bottom edges, straight sides."""
    n = w // step
    top = [f"{i*step}px {0 if i % 2 == 0 else depth}px" for i in range(n + 1)]
    bot = [f"{i*step}px " + ("100%" if i % 2 == 0 else f"calc(100% - {depth}px)")
           for i in range(n, -1, -1)]
    return "polygon(" + ", ".join(top + bot) + ")"


def to_html(data):
    css = CSS.replace("%CLIP%", clip_path(340)).replace("%W%", "340")
    esc = html.escape
    pcount = data["project_count"]
    icount = work_item_count(data)
    t0, t1 = time_window(data)
    ref = "#" + data["date"].replace("-", "")

    P = [f"<!doctype html><html><head><meta charset='utf-8'>"
         # set the animate-in class before first paint so the paper starts hidden (no flash)
         "<script>if(location.hash.indexOf('in')>=0)document.documentElement.className='anim-in';</script>"
         f"<style>{css}</style></head>"
         "<body><div class='surface'><div class='roll'><div class='receipt'>"]

    # masthead (doubles as the drag handle)
    P.append("<button class='hide' onclick=\"send({action:'hide'})\" title='Hide (⌥⌃⌘W to reopen)'>✕</button>")
    P.append("<div class='grip' onmousedown='drag(event)'>")
    P.append("<div class='brand'>E<b>O</b>D</div>")
    P.append("<div class='tag'>DAILY WORK RECEIPT</div>")
    P.append("<div class='stamp'>WORK · SCREEN · WEB</div>")
    P.append("</div>")
    P.append("<div class='rule'></div>")
    P.append(f"<div class='kv'><span class='k'>Date</span><span class='dots'></span><span class='v'>{esc(pretty_date(data['date']))}</span></div>")
    P.append(f"<div class='kv'><span class='k'>Ref</span><span class='dots'></span><span class='v'>{ref}</span></div>")
    today_iso = datetime.now().astimezone().strftime("%Y-%m-%d")
    P.append("<div class='nav'>"
             "<button onclick='nav(-1)' title='Previous day'>◀</button>"
             f"<input type='date' class='dpick' value='{data['date']}' max='{today_iso}' "
             "onchange='goDate(this.value)' title='Jump to date'>"
             "<button onclick='nav(1)' title='Next day'>▶</button>"
             "<button onclick='refresh()' title='Refresh'>↻</button>"
             "</div>")
    P.append("<div class='rule double'></div>")

    apps = data.get("apps", [])
    web  = data.get("web", [])
    app_total = sum(a["secs"] for a in apps)
    web_total = sum(d["count"] for d in web)

    if not (data["projects"] or apps or web):
        P.append("<div class='empty'>— NO ACTIVITY LOGGED —</div>")
    else:
        # ── Work: curated AI highlights (the manager-ready update; editable) ──
        if data.get("highlights"):
            edited_note = " <span class='edot' title='hand-edited'>✎</span>" if data.get("edited") else ""
            P.append("<div class='depthead'><span class='nm'>WORK" + edited_note + "</span>"
                     "<span class='dots'></span>"
                     f"<span class='qty'>×{len(data['highlights'])}</span>"
                     "<button class='cp' onclick=\"copyEl('workText','Work update copied')\" title='Copy work update'>⧉</button>"
                     "<button class='cp' id='editBtn' onclick='toggleEdit()' title='Edit lines'>✎</button>"
                     "<button class='cp' onclick='regen()' title='Re-summarize with AI'>⟳</button>"
                     "</div>")
            P.append("<div class='dept' id='workList' data-edit='0'>")
            for h in data["highlights"]:
                P.append("<div class='item'>"
                         f"<span class='t'><b>•</b><span class='htext'>{esc(h)}</span></span></div>")
            P.append("</div>")
            P.append(f"<div id='workText' style='display:none'>{esc(highlights_text(data))}</div>")
        # ── Fallback: per-project view (only when AI polish unavailable) ──
        elif data["projects"]:
            P.append("<div class='sect'>WORK</div>")
            for i, p in enumerate(data["projects"]):
                pid = f"p{i}"
                items = display_items(p)
                P.append("<div class='dept'><div class='depthead'>")
                P.append(f"<span class='nm'>{esc(p['name'])}</span>")
                P.append("<span class='dots'></span>")
                P.append(f"<span class='qty'>×{len(items)}</span>")
                P.append(f"<button class='cp' onclick=\"copyEl('{pid}','{esc(p['name'])} copied')\">⧉</button>")
                P.append("</div>")
                for it in items:
                    tm = f"<span class='tm'>{it['time']}</span>" if it.get("time") else ""
                    P.append("<div class='item'>"
                             f"<span class='t'><b>•</b>{esc(it['text'])}</span>{tm}</div>")
                P.append("</div>")
                P.append(f"<div id='{pid}' style='display:none'>{esc(project_text(p))}</div>")

        # ── Screen time (app usage) ──
        if apps:
            P.append("<div class='rule'></div>")
            P.append("<div class='depthead'><span class='nm'>SCREEN TIME</span>"
                     "<span class='dots'></span>"
                     f"<span class='qty'>{fmt_dur(app_total)}</span>"
                     "<button class='cp' onclick=\"copyEl('appsText','Screen time copied')\">⧉</button></div>")
            for a in apps[:BRIEF_APPS]:
                P.append(f"<div class='kv'><span class='k'>{esc(a['name'])}</span>"
                         "<span class='dots'></span>"
                         f"<span class='v'>{fmt_dur(a['secs'])}</span></div>")
            P.append(f"<div id='appsText' style='display:none'>{esc(apps_text(data))}</div>")

        # ── Web (browser history) ──
        if web:
            P.append("<div class='rule'></div>")
            P.append("<div class='depthead'><span class='nm'>WEB</span>"
                     "<span class='dots'></span>"
                     f"<span class='qty'>×{web_total}</span>"
                     "<button class='cp' onclick=\"copyEl('webText','Web activity copied')\">⧉</button></div>")
            for d in web[:BRIEF_WEB]:
                P.append("<div class='item'>"
                         f"<span class='t'><b>•</b>{esc(d['host'])}</span>"
                         f"<span class='tm'>×{d['count']}</span></div>")
            P.append(f"<div id='webText' style='display:none'>{esc(web_text(data))}</div>")

    # totals
    P.append("<div class='rule'></div>")
    P.append(f"<div class='kv tot'><span class='k'>Projects</span><span class='dots'></span><span class='v'>{pcount}</span></div>")
    P.append(f"<div class='kv tot'><span class='k'>Work items</span><span class='dots'></span><span class='v'>{icount}</span></div>")
    if apps:
        P.append(f"<div class='kv tot'><span class='k'>Screen</span><span class='dots'></span><span class='v'>{fmt_dur(app_total)}</span></div>")
    if web:
        P.append(f"<div class='kv tot'><span class='k'>Sites</span><span class='dots'></span><span class='v'>{len(web)}</span></div>")
    P.append(f"<div class='kv tot'><span class='k'>From</span><span class='dots'></span><span class='v'>{t0}</span></div>")
    P.append(f"<div class='kv tot'><span class='k'>To</span><span class='dots'></span><span class='v'>{t1}</span></div>")
    P.append("<div class='rule double'></div>")

    P.append("<div class='end'>END OF DAY</div>")
    P.append("<div class='barcode'></div>")
    P.append(f"<div class='bcnum'>{data['date'].replace('-','')} · AG</div>")
    P.append("<div class='actions'>"
             "<button class='copyall' onclick=\"copyEl('allText','Summary copied')\">⎙ Copy</button>"
             "<button class='copyall seeall' onclick=\"send({action:'full'})\">⊞ See full bill</button>"
             "</div>")
    P.append(f"<div class='ts'>updated {esc(data['generated_at'][11:16])} · ~/.claude · <span class='sig'>{esc(_SIG)}</span></div>")

    P.append(f"<div id='allText' style='display:none'>{esc(to_text(data))}</div>")
    P.append("</div></div></div>")  # receipt, roll, surface
    P.append("<div class='toast' id='toast'></div>")
    P.append(f"<script>{JS}</script></body></html>")
    out = "".join(P)
    if _SIG not in out:   # tamper-guard: restore the mark even if the line above is removed
        out = out.replace("</body>", "<div class='ts'><span class='sig'>" + _SIG + "</span></div></body>")
    return out


def to_html_full(data):
    """The 'See full bill' card: everything, in detail (opened as a second window)."""
    css = CSS.replace("%CLIP%", clip_path(520)).replace("%W%", "520")
    esc = html.escape
    apps = data.get("apps", [])
    web  = data.get("web", [])

    P = [f"<!doctype html><html><head><meta charset='utf-8'>",
         "<script>if(location.hash.indexOf('in')>=0)document.documentElement.className='anim-in';</script>",
         f"<style>{css}</style></head>",
         "<body><div class='surface'><div class='roll'><div class='receipt'>"]

    P.append("<button class='hide' onclick=\"send({action:'hide'})\" title='Close'>✕</button>")
    P.append("<div class='grip' onmousedown='drag(event)'>")
    P.append("<div class='brand'>E<b>O</b>D</div>")
    P.append("<div class='tag'>FULL BILL · ALL ACTIVITY</div>")
    P.append("</div>")
    P.append("<div class='rule'></div>")
    P.append(f"<div class='kv'><span class='k'>Date</span><span class='dots'></span><span class='v'>{esc(pretty_date(data['date']))}</span></div>")
    P.append("<div class='rule double'></div>")

    if not (data["projects"] or apps or web or data.get("commits") or data.get("meetings")):
        P.append("<div class='empty'>— NO ACTIVITY LOGGED —</div>")
    else:
        # Curated, readable detailed breakdown (same voice as the brief, just more granular).
        if data.get("detailed"):
            P.append("<div class='sect'>WORK — DETAILED</div>")
            for g in data["detailed"]:
                P.append("<div class='dept'><div class='depthead'>")
                P.append(f"<span class='nm'>{esc(g['area'])}</span><span class='dots'></span>")
                P.append(f"<span class='qty'>×{len(g['items'])}</span></div>")
                for it in g["items"]:
                    P.append("<div class='item'>"
                             f"<span class='t'><b>•</b>{esc(it)}</span></div>")
                P.append("</div>")
        # Fallback: only if AI detail isn't available — raw per-session view.
        elif data["projects"]:
            P.append("<div class='sect'>CLAUDE CODE</div>")
            for p in data["projects"]:
                P.append("<div class='dept'><div class='depthead'>")
                P.append(f"<span class='nm'>{esc(p['name'])}</span><span class='dots'></span>")
                P.append(f"<span class='qty'>×{len(p['sessions'])}</span></div>")
                for s in p["sessions"]:
                    P.append("<div class='item'>"
                             f"<span class='t'><b>•</b>{esc(clean_title(oneline(s['title'], 90)))}</span>"
                             f"<span class='tm'>{s['start']}</span></div>")
                    for pr in s["prompts"]:
                        P.append("<div class='item subt'>"
                                 f"<span class='t'>{esc(oneline(pr['text'], 150))}</span>"
                                 f"<span class='tm'>{pr['t']}</span></div>")
                P.append("</div>")
        if data.get("commits") or data.get("prs"):
            P.append("<div class='rule'></div><div class='sect'>SHIPPED</div>")
            for p in data.get("prs", []):
                P.append("<div class='item'>"
                         f"<span class='t'><b>•</b>PR #{p['number']} — {esc(p['title'])} "
                         f"<span class='dim'>{esc(p['repo'])}</span></span>"
                         f"<span class='tm'>{esc(p['state'])}</span></div>")
            byrepo = {}
            for c in data.get("commits", []):
                byrepo.setdefault(c["repo"], []).append(c)
            for repo, cs in byrepo.items():
                P.append("<div class='dept'><div class='depthead'>")
                P.append(f"<span class='nm'>{esc(repo)}</span><span class='dots'></span>")
                P.append(f"<span class='qty'>×{len(cs)}</span></div>")
                for c in cs:
                    P.append("<div class='item'>"
                             f"<span class='t'><b>•</b>{esc(c['subject'])}</span></div>")
                P.append("</div>")
        if data.get("meetings"):
            P.append("<div class='rule'></div><div class='sect'>MEETINGS</div>")
            for m in data["meetings"]:
                att = f" · {esc(m['attendees'])}" if m.get("attendees") else ""
                P.append("<div class='item'>"
                         f"<span class='t'><b>•</b>{esc(m['title'])}{att}</span>"
                         f"<span class='tm'>{esc(m['time'])}</span></div>")
        if data.get("docs"):
            P.append("<div class='rule'></div><div class='sect'>DOCUMENTS</div>")
            for d in data["docs"]:
                P.append("<div class='item'>"
                         f"<span class='t'><b>•</b>{esc(d['name'])}</span>"
                         f"<span class='tm'>{esc(d['folder'])}</span></div>")
        if apps:
            P.append("<div class='rule'></div><div class='sect'>SCREEN TIME</div>")
            for a in apps[:APP_MAX]:
                P.append(f"<div class='kv'><span class='k'>{esc(a['name'])}</span>"
                         "<span class='dots'></span>"
                         f"<span class='v'>{fmt_dur(a['secs'])}</span></div>")
        if web:
            P.append("<div class='rule'></div><div class='sect'>WEB</div>")
            for d in web:
                P.append("<div class='item'>"
                         f"<span class='t'><b>•</b>{esc(d['host'])}</span>"
                         f"<span class='tm'>×{d['count']}</span></div>")
                for t in d["titles"]:
                    P.append("<div class='item subt'>"
                             f"<span class='t'>{esc(t['title'])}</span>"
                             f"<span class='tm'>{t['t']}</span></div>")

    P.append("<div class='rule double'></div>")
    P.append("<div class='actions'><button class='copyall' onclick=\"copyEl('fullText','Full bill copied')\">⎙ Copy full bill</button></div>")
    P.append(f"<div class='ts'>updated {esc(data['generated_at'][11:16])} · ~/.claude + browser + apps · <span class='sig'>{esc(_SIG)}</span></div>")
    P.append(f"<div id='fullText' style='display:none'>{esc(to_text_full(data))}</div>")
    P.append("</div></div></div>")
    P.append("<div class='toast' id='toast'></div>")
    P.append(f"<script>{JS}</script></body></html>")
    out = "".join(P)
    if _SIG not in out:
        out = out.replace("</body>", "<div class='ts'><span class='sig'>" + _SIG + "</span></div></body>")
    return out


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


def _week_dates(date):
    d = datetime.strptime(date, "%Y-%m-%d").date()
    monday = d - timedelta(days=d.weekday())
    today = datetime.now().astimezone().date()
    end = min(d, today)
    out, cur = [], monday
    while cur <= end:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return monday.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), out


def _day_highlights(date):
    try:
        hl = json.load(open(os.path.join(CACHE, "polish-" + date + ".json"))).get("highlights")
        return hl if isinstance(hl, list) else []
    except Exception:
        return []


def build_weekly(date):
    ws, we, dates = _week_dates(date)
    days = [(d, _day_highlights(d)) for d in dates]
    days = [(d, h) for d, h in days if h]
    data = {"week_start": ws, "week_end": we, "days": days,
            "generated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            "highlights": [], "detailed": []}
    polish_weekly(data)
    return data


def polish_weekly(data):
    if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "polish.off")):
        return
    cb = _claude_bin()
    if not data["days"]:
        return
    raw = "\n".join("## " + pretty_date(d) + "\n" + "\n".join("- " + h for h in hl)
                    for d, hl in data["days"])
    key = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    cache_path = os.path.join(CACHE, "weekly-" + data["week_start"] + ".json")
    try:
        c = json.load(open(cache_path))
        if c.get("key") == key:
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
    json.dump({"key": key, "highlights": hl, "detailed": det}, open(cache_path, "w"))
    data["highlights"] = hl
    data["detailed"] = det


def to_text_weekly(data):
    L = [f"Weekly update — {pretty_date(data['week_start'])} → {pretty_date(data['week_end'])}", ""]
    for h in data.get("highlights", []):
        L.append("• " + h)
    if data.get("detailed"):
        L.append("")
        for g in data["detailed"]:
            L.append(g["area"])
            for it in g["items"]:
                L.append("  - " + it)
    return "\n".join(L).rstrip() + "\n"


def to_html_weekly(data):
    css = CSS.replace("%CLIP%", clip_path(520)).replace("%W%", "520")
    esc = html.escape
    P = ["<!doctype html><html><head><meta charset='utf-8'>",
         "<script>if(location.hash.indexOf('in')>=0)document.documentElement.className='anim-in';</script>",
         f"<style>{css}</style></head>",
         "<body><div class='surface'><div class='roll'><div class='receipt'>"]
    P.append("<button class='hide' onclick=\"send({action:'hide'})\" title='Close'>✕</button>")
    P.append("<div class='grip' onmousedown='drag(event)'>")
    P.append("<div class='brand'>E<b>O</b>D</div>")
    P.append("<div class='tag'>WEEKLY RECAP</div>")
    P.append("</div>")
    P.append("<div class='rule'></div>")
    P.append(f"<div class='kv'><span class='k'>Week</span><span class='dots'></span>"
             f"<span class='v'>{esc(pretty_date(data['week_start']))} → {esc(pretty_date(data['week_end']))}</span></div>")
    P.append("<div class='rule double'></div>")
    if not data.get("highlights"):
        P.append("<div class='empty'>— NO ACTIVITY THIS WEEK —</div>")
    else:
        P.append("<div class='depthead'><span class='nm'>THIS WEEK</span><span class='dots'></span>"
                 f"<span class='qty'>×{len(data['highlights'])}</span>"
                 "<button class='cp' onclick=\"copyEl('wkText','Weekly update copied')\">⧉</button></div>")
        P.append("<div class='dept'>")
        for h in data["highlights"]:
            P.append(f"<div class='item'><span class='t'><b>•</b>{esc(h)}</span></div>")
        P.append("</div>")
        if data.get("detailed"):
            P.append("<div class='rule'></div><div class='sect'>BY AREA</div>")
            for g in data["detailed"]:
                P.append("<div class='dept'><div class='depthead'>")
                P.append(f"<span class='nm'>{esc(g['area'])}</span><span class='dots'></span>"
                         f"<span class='qty'>×{len(g['items'])}</span></div>")
                for it in g["items"]:
                    P.append(f"<div class='item'><span class='t'><b>•</b>{esc(it)}</span></div>")
                P.append("</div>")
    P.append("<div class='rule double'></div>")
    P.append("<div class='end'>END OF WEEK</div>")
    P.append(f"<div id='wkText' style='display:none'>{esc(to_text_weekly(data))}</div>")
    P.append(f"<div class='ts'>updated {esc(data['generated_at'][11:16])} · <span class='sig'>{esc(_SIG)}</span></div>")
    P.append("</div></div></div><div class='toast' id='toast'></div>")
    P.append(f"<script>{JS}</script></body></html>")
    out = "".join(P)
    if _SIG not in out:
        out = out.replace("</body>", "<div class='ts'><span class='sig'>" + _SIG + "</span></div></body>")
    return out


def write_history():
    """Maintain a single readable worklog-history.md from all daily AI summaries."""
    files = sorted(glob.glob(os.path.join(CACHE, "polish-*.json")), reverse=True)
    L = ["# EOD — work history", ""]
    for f in files:
        date = os.path.basename(f)[len("polish-"):-len(".json")]
        try:
            hl = json.load(open(f)).get("highlights") or []
        except Exception:
            continue
        if not hl:
            continue
        L.append("## " + pretty_date(date))
        for h in hl:
            L.append("- " + h)
        L.append("")
    try:
        with open(os.path.join(CACHE, "worklog-history.md"), "w") as fh:
            fh.write("\n".join(L))
    except Exception:
        pass


def main():
    date = None
    do_print = False
    repolish = False
    weekly = False
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--date" and i + 1 < len(args):
            date = args[i + 1]
        elif a == "--print":
            do_print = True
        elif a == "--repolish":
            repolish = True
        elif a == "--weekly":
            weekly = True
    if not date:
        date = datetime.now().astimezone().strftime("%Y-%m-%d")

    os.makedirs(CACHE, exist_ok=True)

    if weekly:                       # build the week's recap and print its html path
        wd = build_weekly(date)
        wbase = os.path.join(CACHE, "weekly-" + wd["week_start"])
        with open(wbase + ".html", "w") as f:
            f.write(to_html_weekly(wd))
        with open(wbase + ".txt", "w") as f:
            f.write(to_text_weekly(wd))
        print("WEEKLY " + wbase + ".html")
        return

    data = build(date)
    polish(data, force=repolish)    # AI-rewrite items into manager bullets (cached; force = Regenerate)
    write_history()                 # keep worklog-history.md current
    base = os.path.join(CACHE, date)

    # Did anything actually change since last run? (ignore the timestamp)
    changed = True
    if os.path.exists(base + ".json"):
        try:
            prev = json.load(open(base + ".json"))
            prev.pop("generated_at", None)
            cur = dict(data); cur.pop("generated_at", None)
            changed = (prev != cur)
        except Exception:
            changed = True

    if changed:
        with open(base + ".json", "w") as f:
            json.dump(data, f)
        with open(base + ".html", "w") as f:
            f.write(to_html(data))
        with open(base + "-full.html", "w") as f:
            f.write(to_html_full(data))
        with open(base + ".txt", "w") as f:
            f.write(to_text(data))
        with open(base + "-full.txt", "w") as f:
            f.write(to_text_full(data))

    # First token tells Hammerspoon whether to reload the webview.
    print(("CHANGED " if changed else "UNCHANGED ") + base + ".html")
    if do_print:
        sys.stderr.write(to_text(data) + "\n")


if __name__ == "__main__":
    main()
