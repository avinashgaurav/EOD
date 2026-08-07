"""Shared test scaffolding: load the eod package in isolation and fake a transcript tree.

The package binds names at import time (`from ..config import ROOT`), so setting
`config.ROOT` after the fact would not reach `sources.claude`. Rather than make
every test know which module holds which name, load_extract returns a facade that
reads across all of them and, crucially, writes through to every module that
already defines the name. Patch once, land everywhere it is actually used.

Each call reloads the package from scratch, so no test can leak state into another.
"""

import contextlib
import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import types
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACT = os.path.join(ROOT_DIR, "extract.py")

MODULES = [
    "eod.util", "eod.config",
    "eod.sources.claude", "eod.sources.codex", "eod.sources.git",
    "eod.sources.web", "eod.sources.apps", "eod.sources.docs",
    "eod.sources.meetings",
    "eod.sources.base", "eod.sources.builtin",
    "eod.pipeline", "eod.polish", "eod.render.text", "eod.render.html",
    "eod.weekly", "eod.cli",
]


class Facade:
    """Flat view over the package. Reads find the first module defining a name;
    writes land on every module that defines it, which is what makes patching a
    from-imported name work at all."""

    def __init__(self, mods):
        object.__setattr__(self, "_mods", mods)

    def __getattr__(self, name):
        for m in self._mods:
            if hasattr(m, name):
                return getattr(m, name)
        raise AttributeError("no module in the eod package defines %r" % name)

    def __setattr__(self, name, value):
        hit = [m for m in self._mods if hasattr(m, name)]
        if not hit:
            raise AttributeError(
                "refusing to set %r: no eod module defines it, so the patch would "
                "silently do nothing" % name)
        for m in hit:
            setattr(m, name, value)

    def modules_defining(self, name):
        return [m.__name__ for m in self._mods if hasattr(m, name)]


def load_extract():
    """A freshly imported eod package with everything that touches the machine stubbed."""
    if ROOT_DIR not in sys.path:
        sys.path.insert(0, ROOT_DIR)
    for name in [m for m in list(sys.modules) if m == "eod" or m.startswith("eod.")]:
        del sys.modules[name]

    mods = []
    with contextlib.redirect_stdout(io.StringIO()):
        for name in MODULES:
            mods.append(importlib.import_module(name))
    ex = Facade(mods)

    # Everything that would read the real machine. A test that cares about one of
    # these re-stubs it; the default is "this source found nothing".
    for fn in ("read_git", "read_github", "read_web", "read_usage",
               "read_docs", "read_meetings"):
        setattr(ex, fn, lambda date, _f=fn: [])
    ex.collect_people = lambda commits, meetings: []
    ex.write_history = lambda: None
    # polish() stays real; what is removed is its only route off the machine, so
    # no test can spawn the CLI or spend a token by accident.
    ex._claude_bin = lambda: None
    return ex


def day_epoch(date, hour=12):
    """Local epoch seconds at `hour` on `date` (YYYY-MM-DD)."""
    y, m, d = (int(x) for x in date.split("-"))
    return time.mktime((y, m, d, hour, 0, 0, 0, 0, -1))


def user_line(text, date, hm="09:30"):
    """One 'user' record, timestamped in UTC the way Claude Code writes them."""
    h, mi = (int(x) for x in hm.split(":"))
    local = day_epoch(date, 0) + h * 3600 + mi * 60
    return json.dumps({
        "type": "user",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(local)),
        "message": {"content": text},
    })


def title_line(title, key="custom-title"):
    """The session-title record. `key` lets a test pin the old or new spelling."""
    field = "aiTitle" if key == "ai-title" else "customTitle"
    return json.dumps({"type": key, field: title})


def fake_subprocess(recorder, result):
    """Stand-in for the subprocess module. Rebinding the name per eod module keeps
    the real stdlib module untouched, so nothing leaks into the next test."""
    return types.SimpleNamespace(run=lambda *a, **k: (recorder.append(1), result)[1])


class TranscriptCase(unittest.TestCase):
    """Base class giving each test a private ~/.claude/projects and ~/.codex tree."""

    def setUp(self):
        self.ex = load_extract()
        self.tmp = tempfile.mkdtemp(prefix="eod-test-")
        self.claude = os.path.join(self.tmp, "projects")
        self.codex = os.path.join(self.tmp, "codex")
        os.makedirs(self.claude)
        os.makedirs(self.codex)
        self.ex.ROOT = self.claude
        self.ex.CODEX_ROOT = self.codex
        self.ex.CACHE = os.path.join(self.tmp, "cache")
        os.makedirs(self.ex.CACHE)
        self.ex.EXCLUDE = set()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_session(self, project, name, lines, mtime_date=None, mtime_hour=12):
        """Write one transcript. mtime is set explicitly: git does not preserve it,
        and the scan filter reads it, so leaving it to chance makes tests flaky."""
        d = os.path.join(self.claude, project)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, name)
        with open(p, "w") as f:
            f.write("\n".join(lines) + "\n")
        if mtime_date:
            t = day_epoch(mtime_date, mtime_hour)
            os.utime(p, (t, t))
        return p

    def write_codex(self, cwd, name, lines, mtime_date=None, mtime_hour=12):
        d = os.path.join(self.codex, "2026", "08", "06")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, name)
        with open(p, "w") as f:
            f.write("\n".join(lines) + "\n")
        if mtime_date:
            t = day_epoch(mtime_date, mtime_hour)
            os.utime(p, (t, t))
        return p
