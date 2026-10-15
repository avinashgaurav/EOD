# Tests

No dependencies, same as the tool. Stdlib `unittest`, fixtures written to a temp
directory so the suite never reads or disturbs your real `~/.claude`.

```sh
./run_tests.sh              # everything
./run_tests.sh -v           # one line per test
./run_tests.sh test_dates   # a single module
```

The suite runs on 3.9 and 3.12 in CI, plus a `luac -p` syntax check and a small
behaviour test (`tests/test_eod_lua.lua`) for the Lua side. It is
run with `-W error::ResourceWarning`, so a leaked file handle fails the build:
the transcript readers leaked one per file before these tests existed.

Two guards worth knowing about, because they are about intent rather than
correctness. CI fails if any of the four config files stops being read by the
engine in `eod/` or disappears from [configuration.md](configuration.md), and
it fails if the hardcoded author signature or its self-restoring guard ever
come back.
