"""Paths, user config files and display limits. Everything tunable in one place."""


import os, html, re, time, subprocess
# The project root, i.e. the directory holding extract.py. Config files and the
# cache live beside it, NOT beside this module: eod.lua and every existing
# install address them by that path, so resolving them relative to the package
# would silently move them.
APP_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def app_path(*parts):
    return os.path.join(APP_DIR, *parts)


ROOT      = os.path.expanduser("~/.claude/projects")


CACHE     = app_path("cache")


CODEX_ROOT = os.path.expanduser("~/.codex/sessions")


# ── git / github / calendar collectors (all local or your own gh/Calendar auth) ──
GIT_ROOTS = ["~/Desktop", "~/Documents", "~/code", "~/dev", "~/projects", "~/work", "~/repos"]


DOC_ROOTS = ["~/Desktop", "~/Downloads", "~/Documents"]


DOC_EXTS = {"pptx", "ppt", "key", "docx", "doc", "pdf", "xlsx", "xls", "csv", "pages", "numbers"}


_DOC_SKIP_DIRS = {"node_modules", ".git", "Library", ".Trash", "cache", ".cache",
                  "venv", ".venv", "dist", "build", "__pycache__", ".next"}


# Projects to keep OFF the receipt (private / job-hunt / NDA) — one name per line in
# exclude.txt next to this script (lines starting with # are comments). Kept in a
# file, not the code, so private names never end up in the repo. Matches a project
# name exactly or any sub-folder of it.
def load_exclude():
    names = set()
    try:
        with open(app_path("exclude.txt")) as fh:
            for line in fh:
                s = line.strip()
                if s and not s.startswith("#"):
                    names.add(s)
    except FileNotFoundError:
        pass
    return names


EXCLUDE = load_exclude()


def is_excluded(pn):
    low = pn.lower()
    if "hammerspoon" in low and "polish" in low:   # EOD's own AI-polish scratch dir — never real work
        return True
    return any(pn == e or pn.startswith(e + "-") for e in EXCLUDE)


def _load_signature():
    """The small mark at the foot of the receipt: YOUR initials, not anyone else's.

    `signature.txt` next to this script wins if it exists, and an empty one means
    no mark at all. Otherwise the initials of your git user.name. Otherwise
    nothing, which renders cleanly rather than leaving a stray separator.
    """
    p = app_path("signature.txt")
    try:
        with open(p) as fh:
            return fh.read().strip()[:6]          # explicit override; "" disables the mark
    except FileNotFoundError:
        pass
    except OSError:
        return ""
    try:
        name = subprocess.run(["git", "config", "--global", "user.name"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""
    words = [w for w in re.split(r"[^A-Za-z]+", name) if w]
    return "".join(w[0].upper() for w in words[:3])


SIG = _load_signature()


def _sig_html():
    """Footer mark, separator included, or nothing at all when there is no mark."""
    return (" · <span class='sig'>%s</span>" % html.escape(SIG)) if SIG else ""


# ── extra sources: app usage + browser history (all local) ─────────────────────
APP_MAX         = 30     # most apps to retain (full card lists all of these)


WEB_MAX_DOMAINS = 30     # most sites to retain (full card lists all of these)


WEB_TITLES_PER  = 6      # page titles retained per site (full card shows all)


APP_MIN_SECS    = 30     # ignore apps with less than this much active time


BRIEF_APPS      = 5      # apps shown on the FIRST (brief) card


BRIEF_WEB       = 6      # sites shown on the FIRST (brief) card (no per-page titles)


CHROME_EPOCH = 11644473600   # seconds from 1601-01-01 to the unix epoch


SAFARI_EPOCH = 978307200     # seconds from 2001-01-01 to the unix epoch


def _full_env():
    """Env that subprocesses (claude/gh/icalBuddy) need to authenticate — Hammerspoon's
    task env omits USER/PATH, which breaks auth."""
    try:
        import pwd
        u = pwd.getpwuid(os.getuid()).pw_name
    except Exception:
        u = os.path.basename(os.path.expanduser("~")) or "user"
    e = dict(os.environ)
    e["HOME"] = os.path.expanduser("~")
    e["USER"] = u
    e["LOGNAME"] = u
    e["PATH"] = ":".join([os.path.expanduser("~/.local/bin"), "/opt/homebrew/bin",
                          "/usr/local/bin", "/usr/bin", "/bin", e.get("PATH", "")])
    return e
