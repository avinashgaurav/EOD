"""WORK: OpenAI Codex rollouts, merged into the same project buckets."""

import json, os, glob, sys, html, re, time, sqlite3, shutil, tempfile, subprocess, hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from ..util import _cwd_key, _predates, _scan_floor, is_noise, local_date_of, oneline
from ..config import CODEX_ROOT, is_excluded


def add_codex(projects, target):
    """Merge OpenAI Codex sessions for `target` into the projects dict (same shape as Claude)."""
    floor = _scan_floor(target)
    for f in glob.glob(os.path.join(CODEX_ROOT, "*", "*", "*", "rollout-*.jsonl")):
        if _predates(f, floor):
            continue
        cwd, title, rows = None, None, []
        try:
            with open(f, errors="replace") as fh:
              for line in fh:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                p = o.get("payload") or {}
                if o.get("type") == "session_meta":
                    cwd = p.get("cwd") or (o.get("payload") or {}).get("cwd")
                    continue
                pt = p.get("type")
                if pt == "thread_name_updated" and p.get("thread_name"):
                    title = p["thread_name"]
                    continue
                if pt != "user_message":
                    continue
                ts = o.get("timestamp")
                if not ts:
                    continue
                day, hm = local_date_of(ts)
                if day != target:
                    continue
                msg = p.get("message")
                if not isinstance(msg, str):
                    continue
                if "<environment_context>" in msg or msg.lstrip().startswith("# Files mentioned by the user"):
                    # keep the actual ask in the "Files mentioned" wrapper, drop the env block
                    m = re.search(r"My request for Codex:\s*(.+)", msg, re.S)
                    msg = m.group(1) if m else ("" if "<environment_context>" in msg else msg)
                msg = oneline(msg, 200) if 'oneline' in globals() else " ".join(msg.split())[:200]
                if msg and not is_noise(msg):
                    rows.append((hm, msg))
        except Exception:
            continue
        if not rows:
            continue
        pn = _cwd_key(cwd) if cwd else "(root)"
        if is_excluded(pn):
            continue
        seen, prompts = set(), []
        for hm, txt in rows:
            k = txt[:64].lower()
            if k in seen:
                continue
            seen.add(k)
            prompts.append((hm, txt))
        if not title:
            title = prompts[0][1][:70]
        projects.setdefault(pn, []).append({
            "sid": "cx" + os.path.basename(f)[8:14],
            "title": title,
            "prompts": prompts,
            "start": prompts[0][0],
            "end": prompts[-1][0],
            "source": "codex",
        })
