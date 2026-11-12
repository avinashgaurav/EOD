"""Assembles one day from every source. The only module that knows them all."""

import os
from datetime import datetime

from .util import pretty_project
from .sources.claude import read_sessions
from .sources.codex import add_codex
from .sources.git import collect_people, read_git, read_github
from .sources.web import read_web
from .sources.apps import read_usage
from .sources.docs import read_docs
from .sources.meetings import read_meetings
from .sources import base as source_registry
from .sources.builtin import register_builtins
from .config import app_path, load_sources_off

register_builtins()
_PLUGIN_ERRORS = source_registry.load_plugins(
    os.environ.get("EOD_SOURCE_DIR") or os.path.expanduser("~/.eod/sources"))


# The day fields the renderers know how to draw. A source claiming one of these
# feeds it directly; anything else is a plugin's own field and goes under "extra",
# where it is kept rather than quietly discarded.
KNOWN_KEYS = {"commits", "prs", "web", "apps", "docs", "meetings"}

# Used when a source names a section but no key of its own.
SECTION_FALLBACK = {"SHIPPED": "commits", "WEB": "web", "SCREEN": "apps",
                    "DOCS": "docs", "MEETINGS": "meetings"}


def collect_sources(target):
    """Run every registered source. Returns (items_by_key, problems).

    A source that is not set up contributes nothing and says nothing. A source
    that IS set up and then fails is recorded, because that is the difference
    the receipt needs to show.
    """
    items, problems, extra = {}, [], {}
    off = load_sources_off()
    for src in source_registry.registry():
        if getattr(src, "assembled_by_pipeline", False) or src.name.lower() in off:
            continue
        got, err = src.collect(target)
        if err:
            problems.append("%s: %s" % (src.name, err))
            continue
        if not got:
            continue
        key = src.key or SECTION_FALLBACK.get(src.section)
        if key in KNOWN_KEYS:
            items.setdefault(key, []).extend(got)
        else:
            # A plugin's own field. Kept under extra so nothing a source produced
            # is thrown away just because no renderer knows about it yet.
            extra.setdefault(key or (src.section or src.name).lower(), []).extend(got)
    if extra:
        items["extra"] = extra
    return items, problems


def build_projects(target):
    """The WORK half of a day: Claude Code and Codex sessions grouped by project.

    Split out so the timesheet export can read sessions without also running
    git, browser history, screen time and the rest for every day of a week.
    Returns (projects, n_sessions, n_untitled, touched).
    """
    off = load_sources_off()
    if "claude-code" in off:
        projects, n_sessions, n_untitled, touched = {}, 0, 0, 0
    else:
        projects, n_sessions, n_untitled, touched = read_sessions(target)
    if "codex" not in off:
        add_codex(projects, target)   # merge Codex sessions into the same project buckets

    # shape output, ordered by busiest project
    out_projects = []
    # Walk the raw project keys in sorted order so the stable sort below falls
    # back to the key itself when everything else ties: pretty names can collide.
    for pn, sessions in sorted(projects.items()):
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
    # Ties need an explicit order: `projects` is filled in glob order, which is
    # readdir order, and ext4 hashes that with a per-disk seed. Without this a new
    # runner image reshuffled equal-sized projects. Earliest start, then name,
    # then the raw key (via the sorted walk above). sessions were sorted by start
    # in the loop, so sessions[0] is the project's earliest session.
    out_projects.sort(key=lambda p: (-p["total"], p["sessions"][0]["start"], p["name"]))
    return out_projects, n_sessions, n_untitled, touched


def sources_status(problems):
    """One line per source for the receipt's footer chips (audit F32):
    ok, off (switched off in Settings), failed, or missing (not set up)."""
    off = load_sources_off()
    failed = {str(p).split(":", 1)[0].strip() for p in problems}
    out = []
    for src in source_registry.registry():
        n = src.name
        if n.lower() in off:
            state = "off"
        elif n in failed:
            state = "failed"
        else:
            try:
                state = "ok" if src.available() else "missing"
            except Exception:
                state = "missing"
        out.append({"name": n, "state": state})
    return out


def build(target):
    """One day, assembled from every source."""
    out_projects, n_sessions, n_untitled, touched = build_projects(target)
    collected, problems = collect_sources(target)
    commits = collected.get("commits", [])
    meetings = collected.get("meetings", [])
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
        "apps": collected.get("apps", []),
        "web": collected.get("web", []),
        "commits": commits,
        "prs": collected.get("prs", []),
        "meetings": meetings,
        "docs": collected.get("docs", []),
        "people": collect_people(commits, meetings),  # collaborators
        # A source that is configured and then fails is not the same as one that
        # is absent, and the receipt should be able to tell you which happened.
        "source_problems": problems + _PLUGIN_ERRORS,
        "sources_status": sources_status(problems + _PLUGIN_ERRORS),
        "extra": collected.get("extra", {}),
    }
