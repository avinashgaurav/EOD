"""Timesheet export: time per project as CSV, for a day or a week.

The number is deliberately simple so anyone can check it by hand. A session's
time is its last prompt minus its first prompt, nothing cleverer. That means:

  - idle time inside a session is counted (lunch between two prompts is work),
  - time after the last prompt is not (the receipt only sees what you typed),
  - a session with a single prompt is 0 minutes,
  - two sessions running side by side are both counted in full, so a project's
    total can exceed the wall-clock time it spanned.

A guess at "real" focus time would be harder to trust than a rule you can
recompute from the receipt itself.
"""

import csv, io, os

from .config import CACHE
from .pipeline import build
from .weekly import _week_dates

COLUMNS = ["date", "project", "source", "start", "end", "minutes", "sessions"]


def _minutes(hm):
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def day_rows(data):
    """One row per (project, source) for one built day.

    Sorted by project then source, not by busiest: a timesheet is read and
    diffed, and alphabetical order is the one that stays put between runs.
    """
    acc = {}
    for p in data.get("projects") or []:
        for s in p.get("sessions") or []:
            key = (p["name"], s.get("source") or "claude")
            r = acc.setdefault(key, {"start": s["start"], "end": s["end"],
                                     "minutes": 0, "sessions": 0})
            r["start"] = min(r["start"], s["start"])
            r["end"] = max(r["end"], s["end"])
            # max(0, ...) because a session is clipped to the day, so end should
            # never precede start; if a clock ever says otherwise, count nothing
            # rather than subtract from the project.
            r["minutes"] += max(0, _minutes(s["end"]) - _minutes(s["start"]))
            r["sessions"] += 1
    return [[data["date"], name, src, r["start"], r["end"], r["minutes"], r["sessions"]]
            for (name, src), r in sorted(acc.items())]


def week_rows(date):
    """Rows for Monday..date (never past today), each day built fresh.

    Built rather than read from CACHE/<date>.json: that file only exists for
    days the widget happened to render, and it can be stale for today. The
    transcripts are the source of truth, so the export reads them.
    """
    _, _, dates = _week_dates(date)
    rows = []
    for d in dates:
        rows.extend(day_rows(build(d)))
    return rows


def to_csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    w.writerows(rows)
    return buf.getvalue()


def export_csv(date, week=False, out=None):
    """Write the CSV and return its path. Default path is in CACHE, beside the
    receipts, named for the day or for the week's Monday."""
    if week:
        rows = week_rows(date)
        name = "timesheet-week-%s.csv" % _week_dates(date)[0]
    else:
        rows = day_rows(build(date))
        name = "timesheet-%s.csv" % date
    path = out or os.path.join(CACHE, name)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", newline="") as f:
        f.write(to_csv(rows))
    return path
