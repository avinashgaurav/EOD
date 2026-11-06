"""The weekly recap: five days folded into one card."""

import json, os
from datetime import datetime, timedelta

from .config import CACHE
from .polish import polish_weekly
from .util import split_problem


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
        with open(os.path.join(CACHE, "polish-" + date + ".json")) as fh:
            hl = json.load(fh).get("highlights")
        return hl if isinstance(hl, list) else []
    except Exception:
        return []


def _day_problems(date):
    """The source failures recorded on that day's receipt, from its cached JSON."""
    try:
        with open(os.path.join(CACHE, date + ".json")) as fh:
            probs = json.load(fh).get("source_problems")
        return [str(p) for p in probs] if isinstance(probs, list) else []
    except Exception:
        return []


def week_source_problems(dates):
    """Every source that failed on any day of the week, once per source.

    The weekly is built from cached highlights, so without this it never saw the
    source layer at all and a week with a broken source looked like a quiet one.
    Keeps the most recent day's detail, since that is the failure still worth
    fixing, and the days it happened on, in date order.
    """
    seen = {}
    for d in dates:
        for p in _day_problems(d):
            name, detail = split_problem(p)
            entry = seen.setdefault(name, {"source": name, "detail": "", "days": []})
            entry["detail"] = detail or "failed"
            if d not in entry["days"]:
                entry["days"].append(d)
    return list(seen.values())


def build_weekly(date, force=False):
    ws, we, dates = _week_dates(date)
    days = [(d, _day_highlights(d)) for d in dates]
    days = [(d, h) for d, h in days if h]
    data = {"week_start": ws, "week_end": we, "days": days,
            "generated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            "highlights": [], "detailed": [],
            "source_problems": week_source_problems(dates)}
    polish_weekly(data, force=force)
    return data
