#!/usr/bin/env python3
"""Re-run the automatic overstatement checks on a saved results file. No model call.

Usage: python3 evals/harness/rescore.py evals/results/<file>.json [evals/datasets/<dataset>.json]
       (pass weeks-new.json for a weekly results file)

Used to test the checks against the 2026-10-15 hand read: on those outputs the
rules should flag the same lines the author found by reading.
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
from eod import polish as P  # noqa: E402
import claims_check as C  # noqa: E402

res = json.load(open(sys.argv[1]))
ds = json.load(open(sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "evals", "datasets", "days.json")))
weekly = "weeks" in ds
if weekly:
    import run_weekly as W  # noqa: E402
cases = {d["id"]: d for d in ds["weeks" if weekly else "days"]}
report = {}
for r in res["results"]:
    case = cases[r["id"]]
    if weekly:
        raw = W.payload(case["data"])
        flags = C.check(C.lines_of(r["output"]), raw, case, W.has_meetings(raw))
    else:
        flags = C.check(C.lines_of(r["output"]), P._polish_input(case["data"]), case, bool(case["data"].get("meetings")))
    report[r["id"]] = flags
    for f in flags:
        print("%s  %-20s %-12s %s" % (r["id"], f["category"], f["detail"][:12], f["line"]))
print(json.dumps({"daysWithOverstatement": sum(1 for v in report.values() if any(f["category"] == "overstated-outcome" for f in v)),
                  "daysWithAddition": sum(1 for v in report.values() if any(f["category"].startswith("added-") for f in v)),
                  "daysClean": sum(1 for v in report.values() if not v)}))
