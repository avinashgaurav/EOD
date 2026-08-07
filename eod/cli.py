"""Entry point. Argument handling and writing the cache."""

import json, os, glob, sys, html, re, time, sqlite3, shutil, tempfile, subprocess, hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from .util import pretty_date
from .config import CACHE, app_path
from .pipeline import build
from .polish import _polish_input, polish
from .render.text import to_text, to_text_full, to_text_weekly
from .render.html import to_html, to_html_full, to_html_weekly
from .weekly import build_weekly


def write_history():
    """Maintain a single readable worklog-history.md from all daily AI summaries."""
    files = sorted(glob.glob(os.path.join(CACHE, "polish-*.json")), reverse=True)
    L = ["# EOD — work history", ""]
    for f in files:
        date = os.path.basename(f)[len("polish-"):-len(".json")]
        try:
            hl = json.load(open(f)).get("highlights") or []
        except Exception:
            continue
        if not hl:
            continue
        L.append("## " + pretty_date(date))
        for h in hl:
            L.append("- " + h)
        L.append("")
    try:
        with open(os.path.join(CACHE, "worklog-history.md"), "w") as fh:
            fh.write("\n".join(L))
    except Exception:
        pass


def main():
    date = None
    do_print = False
    repolish = False
    weekly = False
    show_payload = False
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--date" and i + 1 < len(args):
            date = args[i + 1]
        elif a == "--print":
            do_print = True
        elif a == "--repolish":
            repolish = True
        elif a == "--weekly":
            weekly = True
        elif a == "--show-polish-payload":
            show_payload = True
    if not date:
        date = datetime.now().astimezone().strftime("%Y-%m-%d")

    os.makedirs(CACHE, exist_ok=True)

    if weekly:                       # build the week's recap and print its html path
        wd = build_weekly(date, force=repolish)
        wbase = os.path.join(CACHE, "weekly-" + wd["week_start"])
        with open(wbase + ".html", "w") as f:
            f.write(to_html_weekly(wd))
        with open(wbase + ".txt", "w") as f:
            f.write(to_text_weekly(wd))
        print("WEEKLY " + wbase + ".html")
        return

    data = build(date)

    if show_payload:
        # Print the exact text the polish step would send, and send nothing.
        # The privacy claim in the README should be checkable, not taken on trust.
        payload = _polish_input(data)
        off = os.path.exists(app_path("polish.off"))
        sys.stderr.write(
            "# This is everything AI-polish would send for %s, via your own claude CLI login.\n"
            "# Nothing is being sent now. %s\n"
            "# %d characters. Disable the step for good with: touch polish.off\n\n"
            % (date, "polish.off is present, so the step is already disabled." if off
               else "The step is currently ENABLED.", len(payload)))
        print(payload)
        return

    polish(data, force=repolish)    # AI-rewrite items into manager bullets (cached; force = Regenerate)
    write_history()                 # keep worklog-history.md current
    base = os.path.join(CACHE, date)

    # Did anything actually change since last run? (ignore the timestamp)
    changed = True
    if os.path.exists(base + ".json"):
        try:
            prev = json.load(open(base + ".json"))
            prev.pop("generated_at", None)
            cur = dict(data); cur.pop("generated_at", None)
            changed = (prev != cur)
        except Exception:
            changed = True

    if changed:
        with open(base + ".json", "w") as f:
            json.dump(data, f)
        with open(base + ".html", "w") as f:
            f.write(to_html(data))
        with open(base + "-full.html", "w") as f:
            f.write(to_html_full(data))
        with open(base + ".txt", "w") as f:
            f.write(to_text(data))
        with open(base + "-full.txt", "w") as f:
            f.write(to_text_full(data))

    # First token tells Hammerspoon whether to reload the webview.
    print(("CHANGED " if changed else "UNCHANGED ") + base + ".html")
    if do_print:
        sys.stderr.write(to_text(data) + "\n")
