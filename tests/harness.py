"""Shared test scaffolding: load extract.py in isolation and fake a transcript tree.

extract.py is a script, not a package, and it reads real paths off the machine at
import time. Every test therefore gets its own module instance with the outside
world stubbed out, so a test can never depend on (or disturb) the developer's own
~/.claude, git repos, browser history or calendar.
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACT = os.path.join(ROOT_DIR, "extract.py")


def load_extract():
    """A fresh, isolated extract module with all external readers neutered."""
    spec = importlib.util.spec_from_file_location("extract_under_test", EXTRACT)
    ex = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, ["extract.py"]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            spec.loader.exec_module(ex)
    finally:
        sys.argv = argv

    # Everything that would touch the machine. Tests that care about one of these
    # re-stub it themselves; the default is "this source found nothing".
    ex.read_git = lambda date: []
    ex.read_github = lambda date: []
    ex.read_web = lambda date: []
    ex.read_usage = lambda date: []
    ex.read_docs = lambda date: []
    ex.read_meetings = lambda date: []
    ex.collect_people = lambda commits, meetings: []
    ex.write_history = lambda: None
    # polish() itself is left real: build() never calls it, and the suites that do
    # want it need the genuine article. What is neutered is its only route off the
    # machine, so a test can never spawn the CLI or spend tokens by accident.
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
