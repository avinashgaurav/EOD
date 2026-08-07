"""SCREEN TIME: per-app active seconds, written by eod.lua."""

import json, os, time

from ..config import APP_MIN_SECS, CACHE


def read_usage(date):
    """App active-time for `date`, from cache/usage-YYYY-MM-DD.json (written live by Lua)."""
    p = os.path.join(CACHE, "usage-" + date + ".json")
    try:
        with open(p) as f:
            secs = json.load(f)
    except Exception:
        return []
    apps = [{"name": k, "secs": int(v)} for k, v in secs.items() if int(v) >= APP_MIN_SECS]
    apps.sort(key=lambda a: -a["secs"])
    return apps
