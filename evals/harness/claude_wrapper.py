#!/usr/bin/env python3
"""Eval-only stand-in for the `claude` binary that eod/polish.py spawns.

It runs the real CLI with polish()'s own arguments and prompt, switching only the
output format to the JSON envelope so latency, usage and the answering model can be
logged, and adding the isolation flags if polish() did not pass them. It prints only
the result text, so polish() parses exactly what it would in production.
"""
import json, os, subprocess, sys, time

prompt = sys.stdin.read()
# Use polish()'s own argv. Only the output format changes (text -> json) so usage and
# the answering model can be logged. Isolation flags are added only if polish() did not
# pass them (the pre-fix code path).
args = ["claude"] + sys.argv[1:]
i = args.index("--output-format")
args[i + 1] = "json"
for flag, val in (("--tools", ""), ("--setting-sources", ""), ("--strict-mcp-config", None), ("--no-session-persistence", None)):
    if flag not in args:
        args += [flag] + ([val] if val is not None else [])
rec_argv = args[1:]
if os.environ.get("EVAL_MODEL"):
    args += ["--model", os.environ["EVAL_MODEL"]]
env = dict(os.environ, CLAUDE_CODE_DISABLE_CLAUDE_MDS="1")
t0 = time.time()
r = subprocess.run(args, input=prompt, capture_output=True, text=True, env=env)
ms = int((time.time() - t0) * 1000)
try:
    envl = json.loads(r.stdout)
except Exception:
    envl = None
rec = {"label": os.environ.get("EVAL_LABEL", ""), "argv_from_polish": sys.argv[1:], "ms": ms, "exit": r.returncode,
       "is_error": (envl or {}).get("is_error", True),
       "models": list((envl or {}).get("modelUsage", {}).keys()),
       "usage": (envl or {}).get("usage"), "result_head": ((envl or {}).get("result") or r.stderr or "")[:300]}
rec["limit_hit"] = any(k in (rec["result_head"] + r.stderr).lower() for k in ("usage limit", "limit reached", "rate limit"))
with open(os.environ["EVAL_CALL_LOG"], "a") as f:
    f.write(json.dumps(rec) + "\n")
if not envl or envl.get("is_error"):
    sys.stderr.write(rec["result_head"])
    sys.exit(1)
sys.stdout.write(envl.get("result", ""))
