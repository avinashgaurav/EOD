#!/usr/bin/env bash
# EOD test suite. No dependencies: stdlib unittest, same as the tool itself.
#
#   ./run_tests.sh            run everything
#   ./run_tests.sh -v         verbose, one line per test
#   ./run_tests.sh test_dates run one module
set -euo pipefail

cd "$(dirname "$0")"

PY=${PYTHON:-python3}
echo "python: $($PY --version 2>&1)"

echo
echo "── syntax ──────────────────────────────────────────"
$PY -m py_compile extract.py && echo "  extract.py OK"
if command -v luac >/dev/null 2>&1; then
  luac -p eod.lua init.lua && echo "  eod.lua, init.lua OK"
else
  echo "  lua not installed, skipping eod.lua (CI installs it)"
fi

echo
echo "── tests ───────────────────────────────────────────"
# -W error::ResourceWarning turns a leaked file handle into a failure. The
# transcript readers leaked one per file before the suite existed.
cd tests
if [ $# -gt 0 ] && [[ ${1:-} != -* ]]; then
  exec $PY -W error::ResourceWarning -m unittest "$@"
fi
exec $PY -W error::ResourceWarning -m unittest discover -s . -p 'test_*.py' "$@"
