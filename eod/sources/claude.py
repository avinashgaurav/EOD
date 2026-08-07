"""WORK: Claude Code transcripts."""

import json, os, glob, sys, html, re, time, sqlite3, shutil, tempfile, subprocess, hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from ..util import _day_window, _predates, _scan_floor, _written_during, human_text, local_date_of, proj_name
from ..config import ROOT, is_excluded


def read_sessions(target):
    """Parse Claude Code transcripts for `target`.

    Returns (projects, n_sessions, n_untitled, touched). Knows nothing about the
    other sources or the shape of the finished day; that is the pipeline's job.
    """
    # project -> session_id -> {title, file, prompts:[(hm,text)], start, end}
    projects = {}
    floor = _scan_floor(target)
    win_start, win_end = _day_window(target)
    touched = 0          # transcripts actually written during the target day
    # Named n_* because `sessions` is rebound later by `for pn, sessions in
    # projects.items()`, which silently turned this counter into a list.
    n_sessions = n_untitled = 0
    for f in glob.glob(os.path.join(ROOT, "*", "*.jsonl")):
        if _predates(f, floor):
            continue
        pn = proj_name(f)
        if is_excluded(pn):
            continue
        if _written_during(f, win_start, win_end):
            touched += 1
        title = None
        rows = []  # (hm, text)
        try:
            with open(f, errors="replace") as fh:
              for line in fh:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                t = o.get("type")
                # The session's generated title. Claude Code renamed this record
                # ai-title/aiTitle -> custom-title/customTitle; accept either, else
                # every line degrades to the raw first prompt.
                if t in ("ai-title", "custom-title"):
                    ttl = o.get("aiTitle") or o.get("customTitle")
                    if ttl:
                        title = ttl
                    continue
                ts = o.get("timestamp")
                if not ts:
                    continue
                day, hm = local_date_of(ts)
                if day != target:
                    continue
                txt = human_text(o)
                if txt:
                    rows.append((hm, txt))
        except Exception:
            continue
        if not rows:
            continue
        # de-dup near-identical prompts within the session
        seen, prompts = set(), []
        for hm, txt in rows:
            key = txt[:64].lower()
            if key in seen:
                continue
            seen.add(key)
            prompts.append((hm, txt))
        sid = os.path.basename(f)[:8]
        n_sessions += 1
        if not title:
            n_untitled += 1
            title = prompts[0][1][:70]
        projects.setdefault(pn, []).append({
            "sid": sid,
            "title": title,
            "prompts": prompts,
            "start": prompts[0][0],
            "end": prompts[-1][0],
        })

    return projects, n_sessions, n_untitled, touched
