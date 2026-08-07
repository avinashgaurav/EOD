"""Assembles one day from every source. The only module that knows them all."""

import json, os, glob, sys, html, re, time, sqlite3, shutil, tempfile, subprocess, hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from .util import pretty_project
from .sources.claude import read_sessions
from .sources.codex import add_codex
from .sources.git import collect_people, read_git, read_github
from .sources.web import read_web
from .sources.apps import read_usage
from .sources.docs import read_docs
from .sources.meetings import read_meetings


def build(target):
    """One day, assembled from every source."""
    projects, n_sessions, n_untitled, touched = read_sessions(target)
    add_codex(projects, target)   # merge Codex sessions into the same project buckets

    # shape output, ordered by busiest project
    out_projects = []
    for pn, sessions in projects.items():
        sessions.sort(key=lambda s: s["start"])
        total = sum(len(s["prompts"]) for s in sessions)
        out_projects.append({
            "name": pretty_project(pn), "total": total,
            "sessions": [{
                "title": s["title"], "start": s["start"], "end": s["end"],
                "source": s.get("source", "claude"),
                "prompts": [{"t": t, "text": x} for t, x in s["prompts"]],
            } for s in sessions],
        })
    out_projects.sort(key=lambda p: -p["total"])
    commits = read_git(target)          # SHIPPED — local git commits
    meetings = read_meetings(target)    # MEETINGS — calendar (icalBuddy)
    return {
        "date": target,
        "generated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "projects": out_projects,
        "session_count": sum(len(p["sessions"]) for p in out_projects),
        "project_count": len(out_projects),
        # Transcripts written that day but yielding nothing is a contradiction, and
        # the renderer says so rather than drawing a convincing empty section. An
        # upstream schema rename once blanked WORK for four days without a whisper.
        "transcripts_touched": touched,
        "sessions_seen": n_sessions,
        "sessions_untitled": n_untitled,
        "apps": read_usage(target),     # SCREEN TIME — written by eod.lua, today onward
        "web": read_web(target),        # WEB — parsed from local browser history
        "commits": commits,
        "prs": read_github(target),     # SHIPPED — GitHub PRs (gh active account)
        "meetings": meetings,
        "docs": read_docs(target),      # DOCUMENTS — files you created/edited (decks, docs, sheets)
        "people": collect_people(commits, meetings),  # collaborators
    }
