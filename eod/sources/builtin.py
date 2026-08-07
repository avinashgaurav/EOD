"""The built-in sources, each wrapped in the Source contract.

The reader functions themselves are untouched; this only gives them a uniform
shape and, more importantly, an honest available(). Before this, a missing
icalBuddy and a broken calendar both produced an empty MEETINGS section with no
way to tell which had happened.
"""

import os
import shutil

from ..config import DOC_ROOTS, GIT_ROOTS, ROOT, CODEX_ROOT, app_path
from .base import Source, register
from . import apps, docs, git, meetings, web


class GitSource(Source):
    name = "git"
    section = "SHIPPED"
    key = "commits"
    summary = "Commits you authored today, across local repos"
    requires = "git on PATH, and repos under your work folders or in repos.txt"

    def available(self):
        if not shutil.which("git"):
            return False
        if os.path.exists(app_path("repos.txt")):
            return True
        return any(os.path.isdir(os.path.expanduser(r)) for r in GIT_ROOTS)

    def read(self, date):
        return git.read_git(date)


class GitHubSource(Source):
    name = "github"
    section = "SHIPPED"
    key = "prs"
    summary = "Pull requests you touched today"
    requires = "the gh CLI, authenticated (gh auth status)"

    def available(self):
        return bool(shutil.which("gh"))

    def read(self, date):
        return git.read_github(date)


class WebSource(Source):
    name = "web"
    section = "WEB"
    key = "web"
    summary = "Work pages you spent time on"
    requires = "Chrome, Brave or Safari history (Safari may need Full Disk Access)"

    def available(self):
        # The reader already copies each database before touching it and skips
        # what it cannot find, so "some browser is installed" is the real gate.
        home = os.path.expanduser("~")
        for rel in ("Library/Application Support/Google/Chrome",
                    "Library/Application Support/BraveSoftware/Brave-Browser",
                    "Library/Safari"):
            if os.path.isdir(os.path.join(home, rel)):
                return True
        return False

    def read(self, date):
        return web.read_web(date)


class AppsSource(Source):
    name = "apps"
    section = "SCREEN"
    key = "apps"
    summary = "Where the hours actually went"
    requires = "the widget running; eod.lua writes this file as you work"

    def available(self):
        return os.path.isdir(app_path("cache"))

    def read(self, date):
        return apps.read_usage(date)


class DocsSource(Source):
    name = "docs"
    section = "DOCS"
    key = "docs"
    summary = "Decks, docs, sheets and PDFs you created or edited"
    requires = "at least one of your work folders existing"

    def available(self):
        return any(os.path.isdir(os.path.expanduser(r)) for r in DOC_ROOTS)

    def read(self, date):
        return docs.read_docs(date)


class MeetingsSource(Source):
    name = "meetings"
    section = "MEETINGS"
    key = "meetings"
    summary = "Calendar events for the day"
    requires = "icalBuddy (brew install ical-buddy)"

    def available(self):
        return any(os.path.exists(p) for p in
                   ("/opt/homebrew/bin/icalBuddy", "/usr/local/bin/icalBuddy"))

    def read(self, date):
        return meetings.read_meetings(date)


class ClaudeCodeSource(Source):
    """WORK is assembled by the pipeline rather than collected like the others,
    because Claude and Codex sessions merge into shared project buckets. This
    exists so `eod sources` can still report on it honestly."""

    name = "claude-code"
    section = "WORK"
    summary = "Your Claude Code sessions, per project"
    requires = "~/.claude/projects, i.e. having used Claude Code"
    assembled_by_pipeline = True

    def available(self):
        return os.path.isdir(ROOT)

    def read(self, date):
        return []


class CodexSource(Source):
    name = "codex"
    section = "WORK"
    summary = "Your Codex sessions, merged into the same projects"
    requires = "~/.codex/sessions, i.e. having used Codex"
    assembled_by_pipeline = True

    def available(self):
        return os.path.isdir(CODEX_ROOT)

    def read(self, date):
        return []


BUILTIN = [ClaudeCodeSource, CodexSource, GitSource, GitHubSource,
           WebSource, AppsSource, DocsSource, MeetingsSource]


def register_builtins():
    for cls in BUILTIN:
        register(cls())
