#!/usr/bin/env python3
"""EOD polish fidelity eval.

Calls the real eod.polish.polish(data, force=True): the real POLISH_PROMPT, the real
payload builder (_polish_input), and the real parsing and cleanup (_extract_json_obj,
oneline, _clean_detailed). Only two things are redirected, both eval-only:
  - polish.CACHE  -> a temp dir, so no real cache is read or written
  - polish._claude_bin -> evals/harness/claude_wrapper.py (adds isolation flags, logs usage)

Usage: python3 evals/harness/run.py            (10 CLI calls)
"""
import copy, json, os, re, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from eod import polish as P  # noqa: E402

DS = json.load(open(os.path.join(ROOT, "evals", "datasets", "days.json")))
TMP = tempfile.mkdtemp(prefix="eod-eval-")
CALL_LOG = os.path.join(TMP, "calls.jsonl")
P.CACHE = TMP
P._claude_bin = lambda: os.path.join(HERE, "claude_wrapper.py")
_tl = threading.local()
_orig_env = P._full_env
def _env():
    e = _orig_env()
    e["EVAL_LABEL"] = getattr(_tl, "label", "")
    e["EVAL_CALL_LOG"] = CALL_LOG
    return e
P._full_env = _env
assert not os.path.exists(P.app_path("polish.off")), "polish.off present; polish() would skip"

DICT = set(w.strip().lower() for w in open("/usr/share/dict/words"))
STYLE_OK = set("""engg pr prs mdx csv pdf docx xlsx api ui ux qa ci cd sync standup retro onboarding
backfill backfilled idempotency idempotent redaction configurable lighthouse dashboard widget
one-pager signup setup p95 ms os android ios cms nav mobile tenant tenants per-tenant""".split())

def words(s):
    return re.findall(r"[A-Za-z][A-Za-z'\-]+", s)

def nums(s):
    return set(re.findall(r"\d+(?:\.\d+)?", s))

def score(day, out):
    payload = P._polish_input(day["data"])
    hl = out.get("highlights") or []
    det = out.get("detailed") or []
    all_text = "\n".join(hl + [g["area"] + ": " + " | ".join(g["items"]) for g in det])
    low = all_text.lower()
    misses = []
    dropped = [it["label"] for it in day["items"] if not any(re.search(m, low, re.I) for m in it["markers"])]
    for it in day["items"]:
        if it["label"] in dropped:
            misses.append({"category": "dropped-item-minor" if it.get("minor") else "dropped-item", "detail": it["label"]})
    facts_kept = [f for f in day["facts"] if re.search(f, all_text, re.I)]
    for f in day["facts"]:
        if f not in facts_kept:
            misses.append({"category": "fact-lost", "detail": f})
    for x in day.get("exclude", []):
        if re.search(x, low, re.I):
            misses.append({"category": "trivial-or-personal-included", "detail": x})
    # invented numbers / issue refs: any figure in the output that is not in the payload
    in_nums = nums(payload)
    for n in sorted(nums(all_text) - in_nums):
        misses.append({"category": "invented-number", "detail": n})
    # names that were never sent (meeting attendees are stripped from the payload)
    sent = payload.lower()
    for m in day["data"].get("meetings", []):
        for a in [x.strip() for x in m.get("attendees", "").split(",") if x.strip()]:
            if a.lower() not in sent and re.search(r"\b" + re.escape(a) + r"\b", all_text):
                misses.append({"category": "invented-name", "detail": a + " (attendee, never sent to the model)"})
    # unknown tokens: not in the payload, not an English word, not a known style/tech word -> review
    in_words = set(w.lower() for w in words(payload))
    def known(w):
        w = w.lower().replace("’", "'")
        if w.endswith("'s"):
            w = w[:-2]
        forms = {w, w[:-1], w[:-2], w[:-3], w[:-1] + "e" if w.endswith("d") else w, w[:-3] + "e" if w.endswith("ing") else w,
                 w[:-3] + "y" if w.endswith("ied") else w, w[:-2] if w.endswith("ed") and len(w) > 4 and w[-3] == w[-4] else w}
        return any(f in in_words or f in DICT or f in STYLE_OK for f in forms if f)
    unknown = sorted(set(w for w in words(all_text) if not known(w)))
    return {"dropped": dropped, "facts_kept": len(facts_kept), "facts_total": len(day["facts"]),
            "items_kept": len(day["items"]) - len(dropped), "items_total": len(day["items"]),
            "misses": misses, "unknown_tokens_for_review": unknown,
            "highlight_count": len(hl), "highlights_in_range": 4 <= len(hl) <= 9,
            "highlights_below_min_but_input_has_fewer_items": len(hl) < 4 and len(day["items"]) < 4}

def run_day(day):
    _tl.label = day["id"]
    data = copy.deepcopy(day["data"])
    t0 = time.time()
    P.polish(data, force=True)
    ms = int((time.time() - t0) * 1000)
    out = {"highlights": data.get("highlights"), "detailed": data.get("detailed")}
    if not out["highlights"]:
        return {"id": day["id"], "ms": ms, "ok": False, "misses": [{"category": "polish-failed", "detail": "no highlights; see polish-error.log"}], "output": out}
    s = score(day, out)
    return {"id": day["id"], "ms": ms, "ok": True, "pass": not s["misses"], **s, "output": out}

if __name__ == "__main__":
    only = os.environ.get("EVAL_ONLY")
    days = [d for d in DS["days"] if not only or d["id"] in only.split(",")]
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.time()
    with ThreadPoolExecutor(3) as ex:
        results = list(ex.map(run_day, days))
    wall = int((time.time() - t0) * 1000)
    calls = [json.loads(l) for l in open(CALL_LOG)] if os.path.exists(CALL_LOG) else []
    errlog = open(os.path.join(TMP, "polish-error.log")).read() if os.path.exists(os.path.join(TMP, "polish-error.log")) else ""
    ok = [r for r in results if r["ok"]]
    cats = {}
    for r in results:
        for m in r["misses"]:
            cats[m["category"]] = cats.get(m["category"], 0) + 1
    ms = sorted(c["ms"] for c in calls)
    summary = {
        "started": started, "wallMs": wall, "configuredModel": "CLI default (polish.py passes no --model)",
        "modelsAnswered": sorted(set(m for c in calls for m in c["models"])),
        "cliCalls": len(calls), "cliErrors": sum(1 for c in calls if c["is_error"]),
        "callLatencyMs": {"n": len(ms), "p50": ms[len(ms) // 2] if ms else None, "p90": ms[min(len(ms) - 1, int(len(ms) * 0.9))] if ms else None, "max": ms[-1] if ms else None},
        "usageTotals": {"input": sum((c["usage"] or {}).get("input_tokens", 0) + (c["usage"] or {}).get("cache_read_input_tokens", 0) + (c["usage"] or {}).get("cache_creation_input_tokens", 0) for c in calls),
                        "output": sum((c["usage"] or {}).get("output_tokens", 0) for c in calls)},
        "days": len(results), "polishSucceeded": len(ok),
        "daysWithNoMisses": sum(1 for r in results if r.get("pass")),
        "itemsKept": sum(r.get("items_kept", 0) for r in ok), "itemsTotal": sum(len(d["items"]) for d in days),
        "factsKept": sum(r.get("facts_kept", 0) for r in ok), "factsTotal": sum(len(d["facts"]) for d in days),
        "highlightCountInRange": sum(1 for r in ok if r["highlights_in_range"]),
        "highlightCountBelowMinOnSmallDays": sum(1 for r in ok if r["highlights_below_min_but_input_has_fewer_items"]),
        "missCategories": cats,
        "unknownTokensForManualReview": sorted(set(t for r in ok for t in r["unknown_tokens_for_review"])),
    }
    tag = os.environ.get("EVAL_TAG")
    out = os.path.join(ROOT, "evals", "results", started[:10] + "-claude-cli" + ("-partial" if only else "") + ("-" + tag if tag else "") + ".json")
    json.dump({"method": "Claude Code CLI via eod.polish.polish() (the production path is also the claude CLI); isolation flags added by an eval-only wrapper", "summary": summary, "results": results, "calls": calls, "polishErrorLog": errlog}, open(out, "w"), indent=2)
    print(json.dumps(summary, indent=2))
    print("wrote", out)
