"""Entry point. Argument handling and writing the cache."""

import json, os, glob, re, sys, html
from datetime import datetime

from .util import pretty_date
from .config import CACHE, app_path
from .pipeline import build
from .polish import _polish_input, polish
from .render.text import to_text, to_text_full, to_text_weekly
from .render.html import SHARE_H, SHARE_W, to_html, to_html_full, to_html_share, to_html_weekly
from .render.image import html_to_png
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


def _valid_date(s):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", s or ""):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def share_image(data):
    """Draw the share card to cache/<date>-share.png and print its path."""
    try:
        with open(os.path.join(CACHE, "polish-" + data["date"] + ".json")) as fh:
            hl = json.load(fh).get("highlights")
        if isinstance(hl, list):
            data["highlights"] = [h for h in hl if isinstance(h, str) and h.strip()]
    except Exception:
        pass                           # never polished: the card shows totals only
    base = os.path.join(CACHE, data["date"])
    with open(base + "-share.html", "w") as f:
        f.write(to_html_share(data))
    why = html_to_png(base + "-share.html", base + "-share.png", SHARE_W, SHARE_H)
    if why:
        sys.stderr.write("EOD: no share image: %s\n" % why)
        raise SystemExit(1)
    print("SHARE " + base + "-share.png")


def main():
    date = None
    do_print = False
    repolish = False
    weekly = False
    show_payload = False
    share = False
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
        elif a == "--share":
            share = True
    if not date:
        date = datetime.now().astimezone().strftime("%Y-%m-%d")
    if share and not _valid_date(date):
        sys.stderr.write("EOD: --date wants YYYY-MM-DD, got %r\n" % date)
        raise SystemExit(2)

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

    if share:
        # Before polish on purpose: a press of the share button must never send
        # anything to claude or rewrite the history file. It uses whatever
        # summary the panel already has (cached or hand-edited), or none.
        share_image(data)
        return

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
