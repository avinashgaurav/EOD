"""MEETINGS: calendar, via icalBuddy when it is installed."""

import os, re, time, subprocess
from datetime import datetime

from ..config import _full_env


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
