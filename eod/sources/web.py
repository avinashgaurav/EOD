"""WEB: what you read, from local browser history."""

import json, os, glob, sys, html, re, time, sqlite3, shutil, tempfile, subprocess, hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from ..util import _day_epoch, _is_personal, host_of, oneline
from ..config import CHROME_EPOCH, SAFARI_EPOCH, WEB_MAX_DOMAINS, WEB_TITLES_PER


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
