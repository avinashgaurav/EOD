"""Features built on the receipts EOD already keeps (audit B1, B4 to B7, B11,
B13, B14). Everything here reads the local cache; nothing leaves the Mac
except the optional AI step, which follows the same choice as AI tidy-up."""

import calendar, glob, html, json, os, re
from datetime import datetime, timedelta

from .config import CACHE, app_path
from .util import pretty_date

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── reading the cache ──────────────────────────────────────────────────────────
def day_lines(date):
    """The day's final work lines (AI summary or your edits), or []."""
    try:
        with open(os.path.join(CACHE, "polish-%s.json" % date)) as fh:
            hl = json.load(fh).get("highlights")
        return [h for h in hl if isinstance(h, str) and h.strip()] if isinstance(hl, list) else []
    except (OSError, ValueError):
        return []


def visible_lines(date):
    """The day's lines as anything leaving EOD should see them: hide rules
    applied. Redaction happens at the edge, on the final text."""
    from .hide import hide_lines
    return hide_lines(day_lines(date))


def day_json(date):
    try:
        with open(os.path.join(CACHE, "%s.json" % date)) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def days_with_lines():
    out = []
    for f in glob.glob(os.path.join(CACHE, "polish-*.json")):
        d = os.path.basename(f)[len("polish-"):-len(".json")]
        if DAY_RE.match(d) and day_lines(d):
            out.append(d)
    return sorted(out)


def _shift(date, n):
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=n)).strftime("%Y-%m-%d")


def previous_workday(date):
    d = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


# ── B11: redaction before anything leaves ──────────────────────────────────────
_REDACT = [
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}\b"), "[key]"),
    (re.compile(r"\b(?:ghp|gho|ghs|github_pat|xox[abpr]|lin_api)_[A-Za-z0-9_]{10,}\b"), "[token]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[key]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b"), "[token]"),
    (re.compile(r"\b[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"), "[email]"),
    # Hostnames only: every label starts with a letter, so v1.2.local stays as is.
    (re.compile(r"\b[A-Za-z][\w-]*(?:\.[A-Za-z][\w-]*)*\.(?:internal|corp|lan|intranet)\b(?!\.)"), "[host]"),
    (re.compile(r"/Users/[^/\s]+"), "~"),
    (re.compile(r"https://hooks\.slack\.com/\S+"), "[webhook]"),
]


def redaction_on():
    return not os.path.exists(app_path("redact.off"))


def redact(text):
    """Secrets, emails, internal hostnames and home paths become placeholders.
    On by default; Settings can turn it off (redact.off)."""
    if not text or not redaction_on():
        return text
    for rx, repl in _REDACT:
        text = rx.sub(repl, text)
    return text


# ── B1: the morning standup ────────────────────────────────────────────────────
def morning_standup(date):
    """Yesterday / Today / Blockers, from evidence: yesterday's lines, today's
    meetings and PRs still open."""
    y = previous_workday(date)
    yesterday = visible_lines(y)
    today = []
    for m in (day_json(date).get("meetings") or []):
        if m.get("title"):
            today.append("%s %s" % (m.get("time", ""), m["title"]))
    for p in (day_json(y).get("prs") or []) + (day_json(date).get("prs") or []):
        if str(p.get("state", "")).upper() == "OPEN":
            line = "Follow up on PR #%s: %s" % (p.get("number"), p.get("title", ""))
            if line not in today:
                today.append(line)
    blockers = []
    for f in sorted(glob.glob(os.path.join(CACHE, "weekly-*.json")), reverse=True)[:1]:
        try:
            with open(f) as fh:
                blockers = ((json.load(fh).get("report") or {}).get("blockers")) or []
        except (OSError, ValueError):
            pass
    if not (yesterday or today):
        return None
    L = ["Standup: %s" % pretty_date(date), "", "Yesterday (%s)" % pretty_date(y)]
    L += ["• " + x for x in yesterday] or ["• Nothing recorded."]
    L += ["", "Today"] + (["• " + x.strip() for x in today] or ["• Nothing scheduled yet."])
    L += ["", "Blockers"] + (["• " + b for b in blockers] or ["• None."])
    from .hide import hide_lines
    # Hide rules cover meetings, PRs and blockers too; then redact the whole text.
    return redact("\n".join(hide_lines(L)) + "\n")


# ── B4: brag doc ───────────────────────────────────────────────────────────────
def brag_lines(start, end):
    out = []
    for d in days_with_lines():
        if start <= d <= end and visible_lines(d):
            out.append((d, visible_lines(d)))
    return out


BRAG_PROMPT = (
    "You are turning a person's daily work updates into a BRAG DOCUMENT for a performance review.\n"
    "Group the work into 4 to 8 themes by impact (what changed for users, the team or the business), most "
    "important first. Under each theme write 2 to 6 past-tense achievement lines that keep numbers, versions, "
    "issue and PR numbers from the input. Never invent results, people or numbers. Merge repeated work.\n"
    "Return ONLY markdown: a one-paragraph summary, then '## <theme>' sections with '- ' bullets.\n\n"
)


def brag_doc(start, end, run_ai=None):
    days = brag_lines(start, end)
    if not days:
        return None
    raw = "\n".join("## %s\n%s" % (d, "\n".join("- " + h for h in hl)) for d, hl in days)
    head = "# Work summary: %s to %s\n\n" % (pretty_date(start), pretty_date(end))
    if run_ai:
        try:
            out = run_ai(BRAG_PROMPT + redact(raw))
            if out and out.strip():
                return redact(head + out.strip() + "\n\n---\n\nBuilt by EOD from %d days of updates.\n" % len(days))
        except Exception:
            pass
    # Without AI: every day's lines, newest last, ready to edit.
    body = "\n\n".join("## %s\n%s" % (pretty_date(d), "\n".join("- " + h for h in hl)) for d, hl in days)
    return redact(head + body + "\n")


# ── B5: search and ask ─────────────────────────────────────────────────────────
def search(query, limit=50):
    """Every past work line containing all the words, newest first."""
    words = [w.lower() for w in re.findall(r"\w+", query or "") if len(w) > 1]
    if not words:
        return []
    hits = []
    for d in reversed(days_with_lines()):
        for h in visible_lines(d):
            low = h.lower()
            if all(w in low for w in words):
                hits.append((d, h))
                if len(hits) >= limit:
                    return hits
    return hits


ASK_PROMPT = (
    "Answer the question using ONLY the dated work lines below. Quote dates. If the lines do not answer it, "
    "say so plainly. Two to five sentences.\n\n"
)


def ask(question, run_ai=None):
    words = [w for w in re.findall(r"\w+", question.lower()) if len(w) > 3]
    lines = []
    for d in reversed(days_with_lines()):
        for h in visible_lines(d):
            if any(w in h.lower() for w in words):
                lines.append("%s: %s" % (d, h))
    lines = lines[:80]
    if not lines:
        return "Nothing in your receipts matches that yet."
    fallback = "AI tidy-up is off or unavailable, so here are the matching lines:\n" + redact("\n".join(lines[:20]))
    if not run_ai:
        return fallback
    try:
        answer = run_ai(ASK_PROMPT + "Question: %s\n\n%s" % (question, redact("\n".join(lines))))
    except Exception:
        answer = None
    return redact(answer.strip()) if answer and answer.strip() else fallback


# ── B6: plan versus done ───────────────────────────────────────────────────────
def _plan_path(date):
    return os.path.join(CACHE, "plan-%s.txt" % date)


def save_plan(date, text):
    lines = [" ".join(l.split())[:200] for l in (text or "").splitlines() if l.strip()][:12]
    with open(_plan_path(date), "w") as fh:
        fh.write("\n".join(lines) + ("\n" if lines else ""))
    return lines


def plan_status(date, done_lines):
    """[(plan line, 'done' | 'open')]: done when a work line shares at least two
    meaningful words with it (or one, for a one-word plan)."""
    try:
        with open(_plan_path(date)) as fh:
            plan = [l.strip() for l in fh if l.strip()]
    except OSError:
        return []
    stop = {"the", "and", "for", "with", "from", "into", "that", "this", "today", "work", "finish", "start"}
    done_words = [set(w for w in re.findall(r"\w+", l.lower()) if len(w) > 2) - stop for l in done_lines]
    out = []
    for p in plan:
        pw = set(w for w in re.findall(r"\w+", p.lower()) if len(w) > 2) - stop
        need = 1 if len(pw) <= 1 else 2
        hit = any(len(pw & dw) >= need for dw in done_words) if pw else False
        out.append((p, "done" if hit else "open"))
    return out


# ── B9: assign a session to a project (for timesheets) ──────────────────────────
def _assign_path():
    return app_path("assign.txt")


def load_assignments():
    """{(date, start, title): project} from assign.txt lines 'date start | title => project'."""
    out = {}
    try:
        with open(_assign_path()) as fh:
            for line in fh:
                if "=>" not in line or "|" not in line or line.lstrip().startswith("#"):
                    continue
                left, project = line.rsplit("=>", 1)
                when, title = left.split("|", 1)
                parts = when.split()
                if len(parts) == 2 and project.strip():
                    out[(parts[0], parts[1], title.strip())] = " ".join(project.split())[:80]
    except OSError:
        pass
    return out


def assign_session(date, start, title, project):
    if not (DAY_RE.match(date or "") and re.match(r"^\d{2}:\d{2}$", start or "")):
        return False
    title, project = " ".join(str(title).split())[:200], " ".join(str(project).split())[:80]
    if not title or not project or "=>" in title or "|" in title:
        return False
    with open(_assign_path(), "a") as fh:
        fh.write("%s %s | %s => %s\n" % (date, start, title, project))
    return True


# ── B13: one gentle insight ────────────────────────────────────────────────────
def insight_on():
    return os.path.exists(app_path("insight.on"))


def daily_insight(data):
    """One non-judgemental line about the day, or None. Off by default."""
    if not insight_on():
        return None
    apps = data.get("apps") or []
    total = sum(a.get("secs", 0) for a in apps)
    if not total:
        return None
    week = []
    d = data["date"]
    for i in range(1, 7):
        prev = day_json(_shift(d, -i))
        t = sum(a.get("secs", 0) for a in prev.get("apps") or [])
        if t:
            week.append(t)
    top = max(apps, key=lambda a: a.get("secs", 0))
    share = round(100 * top["secs"] / total)
    if week and total > max(week):
        return "Your longest focused day this week, mostly in %s (%d%%)." % (top["name"], share)
    return "Most of today was in %s (%d%% of screen time)." % (top["name"], share)


# ── B14: history shelf ─────────────────────────────────────────────────────────
def sent_days():
    try:
        with open(os.path.join(CACHE, "sent-days.json")) as fh:
            v = json.load(fh)
        return set(v) if isinstance(v, list) else set()
    except (OSError, ValueError):
        return set()


def history_month_html(ym, css):
    """A month of receipts as a calendar: which days have a receipt, which were
    sent or copied. Clicking a day opens it."""
    y, m = (int(x) for x in ym.split("-"))
    if not 1 <= m <= 12:
        raise ValueError("month must be 01 to 12")
    have, sent = set(days_with_lines()), sent_days()
    today = datetime.now().strftime("%Y-%m-%d")
    cal = calendar.Calendar(firstweekday=0).monthdatescalendar(y, m)
    esc = html.escape
    prev_ym = (datetime(y, m, 1) - timedelta(days=1)).strftime("%Y-%m")
    next_ym = (datetime(y, m, 28) + timedelta(days=4)).strftime("%Y-%m")
    P = ["<!doctype html><html><head><meta charset='utf-8'><style>", css, """
.shelf{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-top:8px}
.shelf .h{font-size:10.5px;color:var(--ink2);text-align:center;letter-spacing:1px}
.shelf button{min-height:40px;flex-direction:column;gap:2px;font-size:12px;color:var(--ink);border-color:var(--line)}
.shelf button.has{border-color:var(--carbon);color:var(--carbon);font-weight:700}
.shelf button.sent::after{content:"sent";font-size:9px;color:var(--accent);font-weight:400}
.shelf button.out{opacity:.35}
.shelf button.gap{border-style:dashed}
.mhead{display:flex;justify-content:space-between;align-items:center;margin:8px 0}
.legend{font-size:11px;color:var(--ink2);margin-top:10px}
""", "</style></head><body><div class='surface'><div class='roll'><div class='receipt'>",
         "<button class='hide' onclick=\"send({action:'hide'})\" aria-label='Close history'>&times;</button>",
         "<div class='grip' onmousedown='drag(event)'><div class='brand'>E<b>O</b>D</div><div class='tag'>HISTORY</div></div>",
         "<div class='mhead'><button onclick=\"send({action:'month',ym:'%s'})\" aria-label='Previous month'>&lsaquo;</button>"
         "<b>%s</b><button onclick=\"send({action:'month',ym:'%s'})\" aria-label='Next month'>&rsaquo;</button></div>"
         % (prev_ym, esc(datetime(y, m, 1).strftime("%B %Y")), next_ym),
         "<div class='shelf'>"]
    for wd in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
        P.append("<div class='h'>%s</div>" % wd)
    for week in cal:
        for day in week:
            ds = day.strftime("%Y-%m-%d")
            cls = []
            if day.month != m:
                cls.append("out")
            if ds in have:
                cls.append("has")
            if ds in sent:
                cls.append("sent")
            if ds not in have and day.weekday() < 5 and ds < today and day.month == m:
                cls.append("gap")
            label = "%s%s" % (pretty_date(ds), ", receipt" if ds in have else (", no receipt" if ds < today else ""))
            P.append("<button class='%s' onclick=\"send({action:'goDate',date:'%s'})\" aria-label='%s'>%d</button>"
                     % (" ".join(cls), ds, esc(label), day.day))
    P.append("</div><div class='legend'>Bold: a receipt exists. Dashed: a weekday with no receipt, worth back-filling. "
             "Red 'sent': copied or sent that day.</div>")
    P.append("</div></div></div><script>function send(m){try{window.webkit.messageHandlers.eod.postMessage(m);return true}catch(e){return false}}"
             "function drag(e){if(e.button===0)send({action:'dragStart'})}"
             "window.playOut=function(){var h=document.documentElement;h.classList.add('anim-out')};</script></body></html>")
    return "".join(P)
