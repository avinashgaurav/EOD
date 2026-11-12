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


OLLAMA_DEFAULT_MODEL = "llama3.2"


def load_ollama_model():
    """The local model AI-polish should use, or None to keep the claude CLI.

    `ollama.txt` next to this script switches polish to Ollama on this Mac. Its
    first line that is not blank or a # comment names the model; otherwise
    OLLAMA_DEFAULT_MODEL. Read
    on every run, not at import, so the switch needs no reload.
    """
    try:
        with open(app_path("ollama.txt")) as fh:
            for line in fh:
                s = line.strip()
                if s and not s.startswith("#"):
                    return s
        return OLLAMA_DEFAULT_MODEL
    except FileNotFoundError:
        return None
    except (OSError, ValueError):     # unreadable or not UTF-8
        return OLLAMA_DEFAULT_MODEL   # the user asked for local, never fall back to the cloud


def _sig_html():
    """Footer mark, separator included, or nothing at all when there is no mark."""
    return (" · <span class='sig'>%s</span>" % html.escape(SIG)) if SIG else ""


# Where the receipt's Send button posts: a Slack or Teams incoming webhook, or a
# comment on a Linear issue. One destination per line in send.txt next to this
# script. It holds secrets (webhook URLs, an API key), so it is gitignored and
# nothing in EOD ever prints it. No file means no button, and nothing leaves the
# Mac this way. Read on every call, so adding the file needs no restart.
#
#   slack  https://hooks.slack.com/services/...
#   teams  https://example.webhook.office.com/...
#   linear lin_api_...  ENG-123
SEND_FILE = app_path("send.txt")


SEND_LABELS = {"slack": "Slack", "teams": "Teams", "linear": "Linear"}


def load_send_targets():
    """Every line of send.txt, parsed. A line that does not parse is kept as
    {'bad': line_number} so the send can say which line to fix, without ever
    echoing what is on it."""
    # The Mac app keeps destinations in the Keychain and hands them over in this
    # variable for the one --send run, so no secret sits in a file.
    env = _send_env()
    if env is not None:
        lines = env.splitlines()
    else:
        try:
            with open(SEND_FILE) as fh:
                lines = fh.read().splitlines()
        except OSError:
            return []
    out = []
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        kind = parts[0].lower()
        if kind in ("slack", "teams") and len(parts) == 2:
            out.append({"kind": kind, "url": parts[1]})
        elif kind == "linear" and len(parts) == 3:
            out.append({"kind": kind, "key": parts[1], "issue": parts[2]})
        else:
            out.append({"kind": None, "bad": n})
    return out


def send_labels():
    """Display names of the configured destinations, for the button's tooltip.
    A send.txt with only broken lines still shows the button, so pressing it
    can say what is wrong rather than the button silently not being there."""
    labels = _send_labels_env()
    if labels is not None:          # the app passes names only, never the secrets
        return [x for x in labels.split(",") if x]
    seen = []
    for t in load_send_targets():
        name = SEND_LABELS.get(t["kind"], "send.txt")
        if name not in seen:
            seen.append(name)
    return seen


# ── extra sources: app usage + browser history (all local) ─────────────────────
APP_MAX         = 30     # most apps to retain (full card lists all of these)


WEB_MAX_DOMAINS = 30     # most sites to retain (full card lists all of these)


WEB_TITLES_PER  = 6      # page titles retained per site (full card shows all)


APP_MIN_SECS    = 30     # ignore apps with less than this much active time


BRIEF_APPS      = 5      # apps shown on the FIRST (brief) card


BRIEF_WEB       = 6      # sites shown on the FIRST (brief) card (no per-page titles)


CHROME_EPOCH = 11644473600   # seconds from 1601-01-01 to the unix epoch


SAFARI_EPOCH = 978307200     # seconds from 2001-01-01 to the unix epoch


# Secrets handed over by the Mac app are taken OUT of the environment the moment
# the engine starts, so no child process (claude, git, gh, icalBuddy) inherits them.
_SEND_ENV = os.environ.pop("EOD_SEND_TARGETS", None)
_LABELS_ENV = os.environ.pop("EOD_SEND_LABELS", None)


def _send_env():
    global _SEND_ENV
    v = os.environ.pop("EOD_SEND_TARGETS", None)
    if v is not None:
        _SEND_ENV = v
    return _SEND_ENV


def _send_labels_env():
    global _LABELS_ENV
    v = os.environ.pop("EOD_SEND_LABELS", None)
    if v is not None:
        _LABELS_ENV = v
    return _LABELS_ENV


# Sources you switched off, one name per line in sources.off (the Mac app's
# Settings writes it): git, github, web, apps, docs, meetings, claude-code, codex.
def load_sources_off():
    try:
        with open(app_path("sources.off")) as fh:
            return {l.strip().lower() for l in fh if l.strip() and not l.startswith("#")}
    except OSError:
        return set()


def _full_env():
    """Env that subprocesses (claude/gh/icalBuddy) need to authenticate — Hammerspoon's
    task env omits USER/PATH, which breaks auth."""
    try:
        import pwd
        u = pwd.getpwuid(os.getuid()).pw_name
    except Exception:
        u = os.path.basename(os.path.expanduser("~")) or "user"
    e = dict(os.environ)
    e.pop("EOD_SEND_TARGETS", None)       # never hand webhooks or API keys to a child process
    e["HOME"] = os.path.expanduser("~")
    e["USER"] = u
    e["LOGNAME"] = u
    e["PATH"] = ":".join([os.path.expanduser("~/.local/bin"), "/opt/homebrew/bin",
                          "/usr/local/bin", "/usr/bin", "/bin", e.get("PATH", "")])
    return e
