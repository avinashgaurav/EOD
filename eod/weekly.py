"""The weekly recap: five days folded into one card."""

import json, os, glob, sys, html, re, time, sqlite3, shutil, tempfile, subprocess, hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from .config import CACHE
from .polish import polish_weekly


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


def build_weekly(date, force=False):
    ws, we, dates = _week_dates(date)
    days = [(d, _day_highlights(d)) for d in dates]
    days = [(d, h) for d, h in days if h]
    data = {"week_start": ws, "week_end": we, "days": days,
            "generated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            "highlights": [], "detailed": []}
    polish_weekly(data, force=force)
    return data
