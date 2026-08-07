"""Plain-text receipts: what lands on the clipboard."""

import time

from ..util import clean_title, fmt_dur, oneline, pretty_date
from ..config import APP_MAX, BRIEF_APPS, BRIEF_WEB


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


def parse_warning(data):
    """Text for the case that should never happen: transcripts written today, no work found.

    Returns None when things are consistent, including the ordinary quiet day where
    nothing was written and nothing was found.
    """
    n = data.get("transcripts_touched") or 0
    if n and not data.get("projects"):
        return "%d session%s written today, none parsed" % (n, "" if n == 1 else "s")
    # The shape the ai-title -> custom-title rename actually took: sessions parse
    # fine, but every one falls back to its raw first prompt because the title
    # record is no longer where we look. A zero-work check would never see it.
    seen = data.get("sessions_seen") or 0
    un = data.get("sessions_untitled") or 0
    if seen >= 3 and un == seen:
        return "%d sessions, not one with a title" % seen
    return None


def source_warnings(data):
    """One short line per source that was set up and then failed.

    A source that is merely absent contributes nothing here; that is the whole
    point of the available()/read() split. Only genuine failures reach this.
    """
    out = []
    for p in data.get("source_problems") or []:
        name, _, detail = str(p).partition(": ")
        out.append("%s unavailable: %s" % (name, oneline(detail or "failed", 70)))
    return out


def extra_lines(data):
    """Items from a plugin whose key no renderer knows about.

    Shown generically rather than dropped, so a plugin author gets something on
    the receipt without every renderer having to learn about their field.
    """
    lines = []
    for key, items in sorted((data.get("extra") or {}).items()):
        if not items:
            continue
        label = key.replace("_", " ").upper()
        for it in items[:6]:
            if isinstance(it, dict):
                txt = it.get("title") or it.get("subject") or it.get("name") or str(it)
            else:
                txt = str(it)
            lines.append((label, oneline(txt, 90)))
    return lines


def to_text(data):
    """Brief, paste-when-asked summary: the important items, lightly grouped."""
    L = [f"Daily update — {pretty_date(data['date'])}", ""]
    warns = source_warnings(data)
    extras = extra_lines(data)
    # A quiet day is not the same as a day where something broke or a plugin
    # produced items. Returning early on all three lost both.
    if not (data["projects"] or data.get("apps") or data.get("web") or warns or extras):
        w = parse_warning(data)
        L.append("Warning: %s. No activity recorded for this day." % w if w
                 else "No activity recorded for this day.")
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
    for label, txt in extras:
        L.append("%s: %s" % (label.title(), txt))
    for w in warns:
        L.append("! " + w)
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


def to_markdown(data):
    """The day as markdown, for pasting into a PR description, doc or issue.

    Deliberately plain: headings and bullets only, no tables, so it survives
    wherever it is pasted.
    """
    L = ["## %s" % pretty_date(data["date"]), ""]
    if data.get("highlights"):
        L += ["- %s" % h for h in data["highlights"]] + [""]
    elif data.get("projects"):
        for p in data["projects"]:
            L.append("### %s" % p["name"])
            L += ["- %s" % it["text"] for it in display_items(p)]
            L.append("")
    else:
        w = parse_warning(data)
        L += ["_%s_" % (w or "No activity recorded for this day."), ""]
    if data.get("commits"):
        L.append("### Shipped")
        L += ["- `%s` %s" % (c["repo"], c["subject"]) for c in data["commits"]]
        L.append("")
    return "\n".join(L).rstrip() + "\n"
