"""Entry point. Argument handling and writing the cache."""

import json, os, glob, re, sys, html
from datetime import datetime

from .util import pretty_date
from .config import CACHE, SEND_FILE, app_path, load_ollama_model, send_labels
from .pipeline import build
from .polish import OLLAMA_URL, _polish_input, polish
from .render.text import to_text, to_text_full, to_text_weekly
from .render.html import SHARE_H, SHARE_W, to_html, to_html_full, to_html_share, to_html_weekly
from .render.image import html_to_png
from .weekly import build_weekly
from .hide import apply_hide


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
    do_send = False
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
        elif a == "--send":
            do_send = True
        elif a == "--hide" and i + 2 < len(args):
            # Never show this: one rule into hide.txt, then rebuild as usual.
            from .hide import add_hide_rule
            if not add_hide_rule(args[i + 1], args[i + 2]):
                sys.stderr.write("EOD: --hide wants line|site|app and a value\n")
                raise SystemExit(2)
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

    if do_send:
        # The Send button. Imported here, not at the top, so the only module that
        # opens a connection is never even loaded on an ordinary run. It posts
        # what the card already shows and never runs the claude CLI.
        from .send import card_data, send_day
        try:
            if os.stat(SEND_FILE).st_mode & 0o077:
                sys.stderr.write("warning: send.txt is readable by other users; chmod 600 send.txt\n")
        except OSError:
            pass
        sent, failed = send_day(card_data(date, build))
        if failed:
            msg = "; ".join(failed)
            if sent:
                msg = "Sent to %s, but %s" % (", ".join(sent), msg)
            sys.stderr.write(msg + "\n")
            sys.exit(1)
        print("SENT " + ", ".join(sent))
        return

    data = apply_hide(build(date))      # hide.txt: before the AI step, so hidden lines never reach it

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
        model = load_ollama_model()
        to = ("to Ollama on this Mac (model %s at %s). It does not leave the Mac."
              % (model, OLLAMA_URL)) if model else "via your own claude CLI login."
        sys.stderr.write(
            "# This is everything AI-polish would send for %s, %s\n"
            "# Nothing is being sent now. %s\n"
            "# %d characters. Disable the step for good with: touch polish.off\n\n"
            % (date, to, "polish.off is present, so the step is already disabled." if off
               else "The step is currently ENABLED.", len(payload)))
        print(payload)
        return

    polish(data, force=repolish)    # AI-rewrite items into manager bullets (cached; force = Regenerate)
    apply_hide(data)                # and again after: a cached or hand-edited line can match a new rule
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

    # The Send button exists only while send.txt does. Adding or removing that
    # file changes nothing in the day itself, so without this check the button
    # would not appear (or go away) until some unrelated activity came in.
    send_to = send_labels()
    if not changed:
        try:
            with open(base + ".html") as fh:
                changed = ("id='sendBtn'" in fh.read()) != bool(send_to)
        except OSError:
            changed = True

    if changed:
        # Written whole, then swapped in: the weekly reads this file, and a
        # half-written one would quietly drop that day's source failures.
        with open(base + ".json.tmp", "w") as f:
            json.dump(data, f)
        os.replace(base + ".json.tmp", base + ".json")
        with open(base + ".html", "w") as f:
            f.write(to_html(data, send_to=send_to))
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
