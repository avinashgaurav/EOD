"""Entry point. Argument handling and writing the cache."""

import json, os, glob, re, sys, html
from datetime import datetime

from .util import pretty_date
from .config import CACHE, SEND_FILE, app_path, load_ollama_model, send_labels
from .pipeline import build
from .polish import OLLAMA_URL, _polish_input, polish
from .render.text import to_text, to_text_full, to_text_weekly
from .render.html import SHARE_H, SHARE_W, render_id, to_html, to_html_full, to_html_share, to_html_weekly
from .render.image import html_to_png
from .weekly import build_weekly
from .hide import apply_hide
from . import features


def write_history():
    """Maintain a single readable worklog-history.md from all daily AI summaries."""
    files = sorted(glob.glob(os.path.join(CACHE, "polish-*.json")), reverse=True)
    L = ["# EOD work history", ""]
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
    apply_hide(data)                   # hidden lines never reach the image
    data["highlights"] = [features.redact(h) for h in data.get("highlights") or []]   # B11
    base = os.path.join(CACHE, data["date"])
    with open(base + "-share.html", "w") as f:
        f.write(to_html_share(data))
    why = html_to_png(base + "-share.html", base + "-share.png", SHARE_W, SHARE_H)
    if why:
        sys.stderr.write("EOD: no share image: %s\n" % why)
        raise SystemExit(1)
    print("SHARE " + base + "-share.png")


def _extra(cmd, a, date):
    """The commands behind the Mac app's extra features (B1, B4 to B7, B14)."""
    from .polish import run_ai_text
    if cmd == "--morning":
        text = features.morning_standup(date)
        if not text:
            sys.stderr.write("EOD: nothing to put in a standup yet\n")
            raise SystemExit(3)
        sys.stdout.write(text)
    elif cmd == "--search":
        for d, line in features.search(a[0] if a else ""):
            print("%s\t%s" % (d, line))
    elif cmd == "--ask":
        sys.stdout.write((features.ask(a[0] if a else "", run_ai_text) or "") + "\n")
    elif cmd == "--brag":
        start, end = (a + [date, date])[:2]
        if not (_valid_date(start) and _valid_date(end)):
            sys.stderr.write("EOD: --brag wants two dates, YYYY-MM-DD\n")
            raise SystemExit(2)
        doc = features.brag_doc(start, end, run_ai_text)
        if not doc:
            sys.stderr.write("EOD: no updates between those dates\n")
            raise SystemExit(3)
        path = os.path.join(CACHE, "brag-%s-to-%s.md" % (start, end))
        with open(path, "w") as fh:
            fh.write(doc)
        print("BRAG " + path)
    elif cmd == "--history":
        ym = a[0] if a and re.match(r"^\d{4}-(0[1-9]|1[0-2])$", a[0]) else date[:7]
        from .render.html import CSS, clip_path
        css = CSS.replace("%CLIP%", clip_path(520)).replace("%W%", "520")
        path = os.path.join(CACHE, "history-%s.html" % ym)
        with open(path, "w") as fh:
            fh.write(features.history_month_html(ym, css))
        print("HISTORY " + path)
    elif cmd == "--plan-file":
        real = os.path.realpath(a[0]) if a else ""
        if (not real.startswith(os.path.realpath(CACHE) + os.sep) or os.path.islink(a[0])
                or not os.path.isfile(real) or os.stat(real).st_uid != os.getuid()):
            sys.stderr.write("EOD: the plan must be a file EOD wrote in its cache\n")
            raise SystemExit(2)
        with open(real) as fh:
            features.save_plan(date, fh.read(4000))
        print("PLAN " + date)
    elif cmd == "--assign":
        if len(a) != 3 or not features.assign_session(date, a[0], a[1], a[2]):
            sys.stderr.write("EOD: --assign wants HH:MM, the session title and a project name\n")
            raise SystemExit(2)
        print("ASSIGNED " + date)
    elif cmd == "--share-week":
        wd = build_weekly(date)
        apply_hide(wd)
        base = os.path.join(CACHE, "weekly-" + wd["week_start"])
        from .render.html import to_html_share_week
        with open(base + "-share.html", "w") as f:
            f.write(to_html_share_week(wd))
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
    standup = False
    text_file = None
    extra_cmd, extra_args = None, []
    args = sys.argv[1:]
    skip = set()
    for i, a in enumerate(args):
        if i in skip:
            continue
        if a == "--date" and i + 1 < len(args):
            date = args[i + 1]
            skip.add(i + 1)
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
        elif a == "--standup":
            standup = True
        elif a in ("--morning", "--search", "--ask", "--brag", "--history", "--plan-file", "--share-week", "--assign"):
            extra_cmd = a
            n = {"--search": 1, "--ask": 1, "--brag": 2, "--history": 1, "--plan-file": 1, "--assign": 3}.get(a, 0)
            extra_args = args[i + 1:i + 1 + n]
            skip.update(range(i + 1, i + 1 + n))
        elif a == "--text-file" and i + 1 < len(args):
            # Send exactly this text (the weekly report as previewed on the card).
            text_file = args[i + 1]
            skip.add(i + 1)
        elif a == "--hide" and i + 2 < len(args):
            # Never show this: one rule into hide.txt, then rebuild as usual.
            skip.update((i + 1, i + 2))
            from .hide import add_hide_rule
            if not add_hide_rule(args[i + 1], args[i + 2]):
                sys.stderr.write("EOD: --hide wants line|site|app and a value\n")
                raise SystemExit(2)
    if not date:
        date = datetime.now().astimezone().strftime("%Y-%m-%d")
    if extra_cmd:
        return _extra(extra_cmd, extra_args, date)
    if standup:
        # The work update as text, exactly what Copy update and Send share.
        # Used by the app's one-key copy and the reminder's Copy action.
        if not _valid_date(date):
            sys.stderr.write("EOD: --date wants YYYY-MM-DD, got %r\n" % date)
            raise SystemExit(2)
        from .send import card_data
        from .render.text import to_standup
        text = to_standup(card_data(date, build))
        if text is None:
            sys.stderr.write("EOD: no work recorded for %s yet\n" % date)
            raise SystemExit(3)
        sys.stdout.write(text)
        return
    if share and not _valid_date(date):
        sys.stderr.write("EOD: --date wants YYYY-MM-DD, got %r\n" % date)
        raise SystemExit(2)

    os.makedirs(CACHE, exist_ok=True)

    if weekly:                       # build the week's recap and print its html path
        wd = build_weekly(date, force=repolish)
        wbase = os.path.join(CACHE, "weekly-" + wd["week_start"])
        with open(wbase + ".html", "w") as f:
            f.write(to_html_weekly(wd, send_to=send_labels()))
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
        if text_file:
            # Only a plain file the app wrote into the cache, never a symlink or
            # anything elsewhere on disk, and at most 20 KB of it.
            real = os.path.realpath(text_file)
            if (not real.startswith(os.path.realpath(CACHE) + os.sep) or os.path.islink(text_file)
                    or not os.path.isfile(real) or os.stat(real).st_uid != os.getuid()):
                sys.stderr.write("EOD: the text to send must be a file EOD wrote in its cache\n")
                raise SystemExit(2)
            with open(real) as fh:
                exact = fh.read(20000)
            # The person previewed this text; hide rules still apply line by line.
            from .hide import hide_lines
            exact = "\n".join(hide_lines(exact.split("\n")))
            sent, failed = send_day({"date": date, "_send_text": exact})
        else:
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
    # The same goes for an engine update: a page drawn by an older version is
    # redrawn, or the new design only appears once the day's data next changes.
    if not changed:
        try:
            with open(base + ".html", encoding="utf-8") as fh:
                page = fh.read()
            changed = (("id='sendBtn'" in page) != bool(send_to)
                       or f"<meta name='eod-render' content='{render_id()}'>" not in page)
        except (OSError, UnicodeDecodeError):
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
