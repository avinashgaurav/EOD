#!/usr/bin/env python3
"""EOD weekly rollup test: does the weekly summary keep each daily line's outcome?

Calls the real eod.polish.polish_weekly(data, force=True): the real WEEKLY_PROMPT,
the real input it builds from the daily highlights, and the real parsing. The
same two eval-only swaps as run.py: polish.CACHE -> a temp dir, and
polish._claude_bin -> evals/harness/claude_wrapper.py.

Usage: EVAL_TAG=run1 python3 evals/harness/run_weekly.py      (one CLI call per week)
"""
import copy, json, os, re, sys, tempfile, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
from eod import polish as P  # noqa: E402
import claims_check as C  # noqa: E402

DS = json.load(open(os.path.join(ROOT, "evals", "datasets", "weeks-new.json")))
TMP = tempfile.mkdtemp(prefix="eod-eval-weekly-")
CALL_LOG = os.path.join(TMP, "calls.jsonl")
P.CACHE = TMP
P._claude_bin = lambda: os.path.join(HERE, "claude_wrapper.py")
# A developer's own ollama.txt must not turn a Claude-labelled eval into an Ollama one.
P.load_ollama_model = lambda: None
_orig_env = P._full_env
P._full_env = lambda: dict(_orig_env(), EVAL_LABEL="weekly", EVAL_CALL_LOG=CALL_LOG)
assert not os.path.exists(P.app_path("polish.off")), "polish.off present; polish_weekly() would skip"


def payload(data):
    # Same text polish_weekly() builds before it calls the CLI.
    return "\n".join("## " + P.pretty_date(d) + "\n" + "\n".join("- " + h for h in hl) for d, hl in data["days"])


def has_meetings(raw):
    return bool(re.search(r"\b(meeting with|met with)\b", C.HEADER.sub("", raw), re.I))


def nums(s):
    return set(re.findall(r"\d+(?:\.\d+)?", s))


def run_week(week):
    data = copy.deepcopy(week["data"])
    data["days"] = [tuple(x) for x in data["days"]]
    data.update({"highlights": [], "detailed": []})
    t0 = time.time()
    P.polish_weekly(data, force=True)
    ms = int((time.time() - t0) * 1000)
    out = {"highlights": data["highlights"], "detailed": data["detailed"]}
    # polish_weekly() falls back to the dailies, grouped by day, when the CLI fails.
    fallback = [{"area": P.pretty_date(d), "items": h} for d, h in data["days"]]
    if out["detailed"] == fallback:
        return {"id": week["id"], "ms": ms, "ok": False, "misses": [{"category": "polish-failed", "detail": "fell back to dailies"}], "output": out}
    raw = payload(data)
    lines = C.lines_of(out)
    text = "\n".join(lines)
    misses = []
    for it in week["items"]:
        if not any(re.search(m, text, re.I) for m in it["markers"]):
            misses.append({"category": "dropped-item", "detail": it["label"]})
    kept = [f for f in week["facts"] if re.search(f, text, re.I)]
    misses += [{"category": "fact-lost", "detail": f} for f in week["facts"] if f not in kept]
    misses += [{"category": "invented-number", "detail": n} for n in sorted(nums(text) - nums(raw))]
    # A daily "Meeting with Design" line is the week's meeting; "Met with Design" restates it.
    claims = C.check(lines, raw, week, has_meetings(raw))
    misses += claims
    return {"id": week["id"], "ms": ms, "ok": True, "pass": not misses, "misses": misses,
            "items_kept": len(week["items"]) - sum(1 for m in misses if m["category"] == "dropped-item"),
            "items_total": len(week["items"]), "facts_kept": len(kept), "facts_total": len(week["facts"]),
            "overstated": any(m["category"] == "overstated-outcome" for m in claims),
            "added": any(m["category"].startswith("added-") for m in claims),
            "highlight_count": len(out["highlights"]), "output": out}


if __name__ == "__main__":
    started = datetime.now(timezone.utc).isoformat()
    results = [run_week(w) for w in DS["weeks"]]
    calls = [json.loads(l) for l in open(CALL_LOG)] if os.path.exists(CALL_LOG) else []
    ok = [r for r in results if r["ok"]]
    summary = {
        "started": started, "configuredModel": "CLI default (polish.py passes no --model)",
        "modelsAnswered": sorted(set(m for c in calls for m in c["models"])),
        "cliCalls": len(calls), "cliErrors": sum(1 for c in calls if c["is_error"]),
        "costUsdReportedByCli": round(sum(c.get("cost_usd") or 0 for c in calls), 4),
        "weeks": len(results), "polishSucceeded": len(ok),
        "itemsKept": sum(r["items_kept"] for r in ok), "itemsTotal": sum(len(w["items"]) for w in DS["weeks"]),
        "factsKept": sum(r["facts_kept"] for r in ok), "factsTotal": sum(len(w["facts"]) for w in DS["weeks"]),
        "weeksWithOverstatedOutcome": sum(1 for r in ok if r["overstated"]),
        "weeksWithAddition": sum(1 for r in ok if r["added"]),
        "weeksWithNoMisses": sum(1 for r in ok if r["pass"]),
    }
    tag = os.environ.get("EVAL_TAG")
    out = os.path.join(ROOT, "evals", "results", started[:10] + "-claude-cli-weeks-new" + ("-" + tag if tag else "") + ".json")
    json.dump({"method": "Claude Code CLI via eod.polish.polish_weekly(); eval-only wrapper logs usage", "dataset": "weeks-new.json",
               "summary": summary, "results": results, "calls": calls}, open(out, "w"), indent=2)
    print(json.dumps(summary, indent=2))
    print("wrote", out)
