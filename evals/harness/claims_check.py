"""Automatic overstatement and addition checks for a polished update.

The first polish test found overstated outcomes ("shipped" when only a commit
existed) and small additions ("weekly", "worked with Meera") by reading every
output by hand. This module does the same checks with fixed rules, so they run
the same way every time and need no reader.

Two modes:

* Keyed (a case with `outcomes_ok` on its items): each output line is split into
  clauses. A clause is matched to the work items whose markers it mentions; any
  outcome word in it that none of those items allow is an overstatement. A
  clause that names no item falls back to the items its line names, then to
  every item that day. Day-specific `must_not_say` patterns run on every line.
* Keyless (older cases with no key, such as days.json): an outcome word counts
  as supported only if the same word appears in the input text the model saw,
  with EOD's own section headers (which say "SHIPPED" over every commit)
  removed. "met" is supported when the day has a meeting, and "shipped" when the
  day has a merged PR (the prompt's own rule).

Both modes also flag cadence words, team names and "worked with <Name>" that
the input does not support, and meeting words on a day with no meeting.

Limits: these are word rules. They cannot judge a claim that uses none of the
listed words (for example "finished the export" when it was half done), and a
listed word can appear in an innocent sense. Every flag names the line it
came from so a person can check it.
"""
import re

OUTCOMES = {
    "shipped": r"\bshipped\b",
    "merged": r"\bmerged\b",
    "deployed": r"\bdeployed\b|\bwent live\b|\b(is|now) live\b|\brolled out\b",
    "released": r"\breleased\b",
    "launched": r"\blaunched\b",
    "published": r"\bpublished\b|\bposted\b",
    "sent": r"\bsent\b|\bemailed\b|\bsubmitted\b",
    "shared": r"\bshared\b(?! (drive|folder|doc|link|channel|inbox))",
    "approved": r"\bapproved\b|\bsigned off\b",
    "scheduled": r"\bscheduled\b",
    "met": r"\bmet with\b|\bmeeting with\b|\bsynced with\b",
}
CADENCE = r"\b(daily|weekly|bi-?weekly|fortnightly|monthly|quarterly|nightly|hourly|recurring|routine)\b"
# Capitalised team names, as in the prompt's own style examples ("Discussed with Engg").
TEAMS = r"\b(Design|Engg|Engineering|Marketing|Sales|Support|Growth|Legal|Finance|Ops|DevOps|Backend|Frontend|QA|Leadership|Security|Risk|Data team|Product team)\b|\b(?:with|to) (?:the )?(Team)\b"
MEETING = r"\b(meeting|met|call with|synced|sync with|standup|stand-up|1:1|discussed|discussion)\b"
COLLAB = r"\b(?i:worked|working|paired|pairing|partnered|collaborated|teamed up)\s+with\s+([A-Z][a-z]+)"
# A cadence word is fine when the input says the same thing in other words.
CADENCE_SAME = {"daily": r"\b(each|every|per) day\b",
                "weekly": r"\b(each|every|per) (week|monday|tuesday|wednesday|thursday|friday)\b",
                "monthly": r"\b(each|every|per|a) month\b",
                "nightly": r"\b(each|every) night\b"}
HEADER = re.compile(r"^## .*$", re.M)


def lines_of(out):
    """Every output line, with the area name in front of each detailed item."""
    hl = out.get("highlights") or []
    det = out.get("detailed") or []
    return list(hl) + [g["area"] + ": " + it for g in det for it in g["items"]]


def clauses(line):
    return [c for c in re.split(r";|,| and | then | but |: ", line) if c.strip()]


def _items_in(text, items):
    return [it for it in items if any(re.search(m, text, re.I) for m in it["markers"])]


def check(lines, payload, case, has_meetings):
    """Return a list of {category, detail, line} flags for one case."""
    flags = []
    body = HEADER.sub("", payload).lower()
    items = case.get("items", [])
    keyed = any("outcomes_ok" in it for it in items)
    for line in lines:
        # outcome words
        for cl in clauses(line):
            for fam, rx in OUTCOMES.items():
                if not re.search(rx, cl, re.I):
                    continue
                if keyed:
                    hit = _items_in(cl, items) or _items_in(line, items) or items
                    ok = set(x for it in hit for x in it.get("outcomes_ok", []))
                    if fam not in ok:
                        flags.append({"category": "overstated-outcome", "detail": fam, "line": line})
                else:
                    supported = ((fam == "met" and has_meetings)
                                 # the prompt's own rule: a merged PR is evidence for "shipped"
                                 or (fam == "shipped" and "(merged)" in body)
                                 or re.search(rx, body, re.I))
                    if not supported:
                        flags.append({"category": "overstated-outcome", "detail": fam, "line": line})
        # additions
        for m in re.finditer(CADENCE, line, re.I):
            w = m.group(0).lower()
            if w not in body and not re.search(CADENCE_SAME.get(w, r"$^"), body):
                flags.append({"category": "added-cadence", "detail": m.group(0), "line": line})
        for m in re.finditer(TEAMS, line):
            w = (m.group(1) or m.group(2)).lower()
            if w not in body:
                flags.append({"category": "added-team", "detail": m.group(0), "line": line})
        # A day with a calendar meeting may call it a meeting, a sync or a discussion.
        for m in ([] if has_meetings else re.finditer(MEETING, line, re.I)):
            if m.group(0).lower() not in body:
                flags.append({"category": "added-meeting", "detail": m.group(0), "line": line})
        for m in re.finditer(COLLAB, line):
            if m.group(1) not in case.get("collab_ok", []):
                flags.append({"category": "added-collaborator", "detail": m.group(1), "line": line})
        for rule in case.get("must_not_say", []):
            if re.search(rule["re"], line, re.I):
                cat = "overstated-outcome" if rule["kind"] == "overstated" else "added-by-key"
                flags.append({"category": cat, "detail": rule["why"], "line": line})
    # one flag per (category, detail, line)
    seen, out = set(), []
    for f in flags:
        k = (f["category"], f["detail"], f["line"])
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def summarize(flags):
    over = [f for f in flags if f["category"] == "overstated-outcome"]
    add = [f for f in flags if f["category"].startswith("added-")]
    return {"overstated": len(over), "added": len(add)}
