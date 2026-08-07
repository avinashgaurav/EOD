"""SHIPPED: local commits, GitHub PRs, and who you worked with."""

import json, os, re, subprocess

from ..util import oneline
from ..config import GIT_ROOTS, _full_env, app_path


def _git_repos():
    repos = set()
    cfg = app_path("repos.txt")
    try:                                  # optional override/extra list, one path per line
        with open(cfg) as fh:
          for line in fh:
            s = line.strip()
            if s and not s.startswith("#") and os.path.isdir(os.path.join(os.path.expanduser(s), ".git")):
                repos.add(os.path.expanduser(s))
    except FileNotFoundError:
        pass
    for root in GIT_ROOTS:
        r = os.path.expanduser(root)
        if not os.path.isdir(r):
            continue
        try:
            out = subprocess.run(["find", r, "-maxdepth", "3", "-name", ".git"],
                                 capture_output=True, text=True, timeout=15).stdout
            for g in out.splitlines():
                repos.add(os.path.dirname(g))
        except Exception:
            continue
    return sorted(repos)


def read_git(date):
    """Your commits across local repos for `date` (filtered to your git identity)."""
    commits = []
    start, end = date + " 00:00:00", date + " 23:59:59"
    for repo in _git_repos():
        try:
            email = subprocess.run(["git", "-C", repo, "config", "user.email"],
                                   capture_output=True, text=True, timeout=5).stdout.strip()
            args = ["git", "-C", repo, "log", "--no-merges", "--since", start, "--until", end,
                    "--pretty=format:%h\t%s\t%(trailers:key=Co-authored-by,valueonly,separator=;)"]
            if email:
                args += ["--author", email]
            out = subprocess.run(args, capture_output=True, text=True, timeout=10).stdout
            name = os.path.basename(repo)
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                h, subj = parts[0], parts[1]
                co = parts[2] if len(parts) > 2 and not parts[2].startswith("%(") else ""
                coauthors = [re.sub(r"\s*<[^>]*>", "", x).strip() for x in co.split(";") if x.strip()]
                commits.append({"repo": name, "hash": h, "subject": oneline(subj, 100),
                                "coauthors": coauthors})
        except Exception:
            continue
    return commits


def read_github(date):
    """PRs you touched on `date`, via your gh CLI active account (best-effort)."""
    gh = next((p for p in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh") if os.path.exists(p)), None)
    if not gh:
        return []
    try:
        out = subprocess.run([gh, "search", "prs", "--author=@me", "--sort", "updated",
                              "--order", "desc", "--limit", "40", "--json",
                              "number,title,state,repository,createdAt,updatedAt,closedAt"],
                             capture_output=True, text=True, timeout=40, env=_full_env()).stdout
        prs = []
        for p in json.loads(out or "[]"):
            stamps = [p.get("createdAt", ""), p.get("updatedAt", ""), p.get("closedAt", "") or ""]
            if not any(str(s)[:10] == date for s in stamps):   # touched today (UTC ~ close enough)
                continue
            repo = (p.get("repository") or {}).get("name", "")
            prs.append({"number": p.get("number"), "title": oneline(p.get("title", ""), 100),
                        "state": p.get("state", ""), "repo": repo})
        return prs[:20]
    except Exception:
        return []


_PEOPLE_SKIP = ("claude", "bot", "actions", "noreply", "dependabot", "github", "[bot]")


def collect_people(commits, meetings):
    """Collaborators from commit co-authors + meeting attendees (minus you and bots)."""
    try:
        me = subprocess.run(["git", "config", "--global", "user.name"],
                            capture_output=True, text=True, timeout=5).stdout.strip().lower()
    except Exception:
        me = ""
    names = {}
    def add(n):
        n = oneline(n, 40).strip(" ,")
        low = n.lower()
        if not n or "@" in n or any(s in low for s in _PEOPLE_SKIP):
            return
        if me and (low == me or low in me or me in low):
            return
        names.setdefault(low, n)
    for c in commits:
        for n in c.get("coauthors", []):
            add(n)
    for m in meetings:
        for n in re.split(r"[;,]", m.get("attendees", "")):
            add(n)
    return list(names.values())[:12]
