"""Never show this: rules in hide.txt that keep a line, a site or an app off
the receipt, out of the AI step and out of everything copied or sent.

    line: dentist           # any work line containing this text
    site: news.ycombinator.com
    app:  Messages

Matching is case-insensitive. A line rule matches inside the text; site and
app rules match the whole host or app name. Lines starting with # are notes.
Read on every run, so a new rule applies on the next refresh.
"""

import os

from .config import app_path

HIDE_FILE = None          # tests may point this at a file; otherwise resolved per call


def _hide_file():
    return HIDE_FILE or app_path("hide.txt")
KINDS = ("line", "site", "app")


def load_hide_rules(path=None):
    rules = {k: [] for k in KINDS}
    try:
        with open(path or _hide_file()) as fh:
            for raw in fh:
                s = raw.strip()
                if not s or s.startswith("#") or ":" not in s:
                    continue
                kind, value = s.split(":", 1)
                kind, value = kind.strip().lower(), value.strip().lower()
                if kind in rules and value:
                    rules[kind].append(value)
    except OSError:
        pass
    return rules


def add_hide_rule(kind, value, path=None):
    """Append one rule, once. Returns False for an unknown kind or empty value.
    Long lines are cut to 200 characters; the cut text still matches the line."""
    kind, value = str(kind).strip().lower(), " ".join(str(value).split())[:200]
    if kind not in KINDS or not value:
        return False
    if value.lower() in load_hide_rules(path)[kind]:
        return True
    p = path or _hide_file()
    new = not os.path.exists(p)
    with open(p, "a") as fh:
        if new:
            fh.write("# Things EOD never shows. Delete a line to bring it back.\n")
        fh.write("%s: %s\n" % (kind, value))
    return True


def _line_hidden(text, rules):
    low = (text or "").lower()
    return any(r in low for r in rules["line"])


def hide_lines(lines, rules=None):
    """A plain list of strings, minus hidden lines (weekly highlights)."""
    rules = rules or load_hide_rules()
    return [x for x in lines if not _line_hidden(x, rules)] if rules["line"] else list(lines)


def apply_hide(data, rules=None):
    """Drop hidden lines, sites and apps from a day, in place. Safe to call twice."""
    rules = rules or load_hide_rules()
    if not any(rules.values()):
        return data
    if rules["app"]:
        data["apps"] = [a for a in data.get("apps") or [] if a.get("name", "").lower() not in rules["app"]]
    if rules["site"]:
        data["web"] = [d for d in data.get("web") or [] if d.get("host", "").lower() not in rules["site"]]
    if rules["line"]:
        for p in data.get("projects") or []:
            p["sessions"] = [s for s in p.get("sessions") or [] if not _line_hidden(s.get("title"), rules)]
        data["projects"] = [p for p in data.get("projects") or [] if p.get("sessions")]
        if data.get("highlights"):
            data["highlights"] = [h for h in data["highlights"] if not _line_hidden(h, rules)]
        for g in data.get("detailed") or []:
            g["items"] = [i for i in g.get("items") or [] if not _line_hidden(i, rules)]
        if data.get("detailed"):
            data["detailed"] = [g for g in data["detailed"] if g.get("items")]
        for p in data.get("projects") or []:
            for s in p.get("sessions") or []:
                if s.get("prompts"):
                    s["prompts"] = [x for x in s["prompts"] if not _line_hidden(x.get("text") if isinstance(x, dict) else x, rules)]
        data["commits"] = [c for c in data.get("commits") or [] if not _line_hidden(c.get("subject"), rules)]
        data["docs"] = [d for d in data.get("docs") or [] if not _line_hidden(d.get("name"), rules)]
        data["meetings"] = [m for m in data.get("meetings") or [] if not _line_hidden(m.get("title"), rules)]
        data["prs"] = [p for p in data.get("prs") or [] if not _line_hidden(p.get("title"), rules)]
        for d in data.get("web") or []:
            if d.get("titles"):
                d["titles"] = [t for t in d["titles"] if not _line_hidden(t.get("title") if isinstance(t, dict) else t, rules)]
    return data
