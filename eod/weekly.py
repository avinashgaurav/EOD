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


def _day_json(date):
    try:
        with open(os.path.join(CACHE, date + ".json")) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def week_time(dates):
    """Screen time per day and for the week, from each day's cached receipt.

    Counted by code, never by the model: these are the numbers a timesheet
    needs, so they have to be the same every time.
    """
    days, apps = [], {}
    for d in dates:
        secs = 0
        for a in _day_json(d).get("apps") or []:
            try:
                s = int(a.get("secs", 0))
            except (TypeError, ValueError):
                continue
            secs += s
            apps[a.get("name", "?")] = apps.get(a.get("name", "?"), 0) + s
        if secs:
            days.append({"date": d, "secs": secs})
    top = sorted(apps.items(), key=lambda kv: -kv[1])[:3]
    return {"days": days, "total": sum(x["secs"] for x in days),
            "top_apps": [{"name": n, "secs": s} for n, s in top]}


def week_tickets(dates):
    """Pull requests touched this week, newest state wins, plus the commit count."""
    prs, commits = {}, 0
    for d in dates:
        j = _day_json(d)
        commits += len(j.get("commits") or [])
        for p in j.get("prs") or []:
            if not isinstance(p, dict) or p.get("number") is None:
                continue
            prs[(p.get("repo", ""), p.get("number"))] = {
                "repo": p.get("repo", ""), "number": p.get("number"),
                "state": str(p.get("state", "")).upper(), "title": p.get("title", "")}
    by_state = {}
    for pr in sorted(prs.values(), key=lambda x: (x["repo"], str(x["number"]))):
        by_state.setdefault(pr["state"] or "OTHER", []).append(pr)
    return {"prs": by_state, "commits": commits}


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
            "highlights": [], "detailed": [], "report": {},
            "time": week_time(dates), "tickets": week_tickets(dates),
            "source_problems": week_source_problems(dates)}
    polish_weekly(data, force=force)
    return data
