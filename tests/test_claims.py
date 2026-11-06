"""Every behavioural promise the docs make (README.md and docs/), as an executable test.

Three times in one session the README described behaviour the code did not have:
the polish payload, source failures appearing on the receipt, and then the
half-fix of that same thing. Each time the sentence was written before the last
mile of the code, and twice it took someone else to notice.

Remembering not to do that is not a fix. This is: each claim in the docs carries
a `<!--claim:NAME-->` marker, each test here declares the claim it proves, and
tests/test_claim_coverage.py fails the build if the two sets ever diverge. You
cannot add a promise to the docs without also making it falsifiable, and you
cannot quietly drop the behaviour without a red test.

Add a claim => add a test here. Delete a claim => delete its test.
"""

import json
import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

from harness import TranscriptCase, fake_subprocess, load_extract, title_line, user_line

DAY = "2026-08-06"

FAILING = '''
from eod.sources.base import Source, register
class Boom(Source):
    name = "boomsource"; section = "WEB"; key = "web"
    def available(self): return True
    def read(self, date): raise RuntimeError("the token expired")
register(Boom())
'''

ABSENT = '''
from eod.sources.base import Source, register
class Absent(Source):
    name = "absentsource"; section = "WEB"; key = "web"
    requires = "something not installed"
    def available(self): return False
    def read(self, date): raise AssertionError("must not be read")
register(Absent())
'''

PLUGIN = '''
from eod.sources.base import Source, register
class Linear(Source):
    name = "linearsource"; section = "SHIPPED"; key = "linear_issues"
    def available(self): return True
    def read(self, date): return [{"title": "closed ENG-1"}]
register(Linear())
'''

BROKEN = "import a_module_that_certainly_does_not_exist\n"

# Files allowed to import a network module, and which ones. Everything else in
# eod/ may import none of NETWORK_MODULES, anywhere in the file.
NETWORK_ALLOWED = {"eod/polish.py": {"urllib.request", "urllib.error"}}

NETWORK_MODULES = ("urllib.request", "urllib.error", "http.client", "socket", "ssl",
                   "smtplib", "ftplib", "urllib3", "requests", "httpx", "aiohttp", "asyncio")


def _network_imports(node):
    """The network modules an Import/ImportFrom node pulls in, e.g. both
    `import urllib.request` and `from urllib import request` give urllib.request."""
    import ast
    if isinstance(node, ast.Import):
        names = [a.name for a in node.names]
    elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
        names = [node.module] + [node.module + "." + a.name for a in node.names]
    else:
        return set()
    hits = set()
    for n in names:
        for m in NETWORK_MODULES:
            if n == m or n.startswith(m + "."):
                hits.add(m)
    return hits


class FakeRun:
    returncode = 0
    stdout = '{"highlights": ["bullet"], "detailed": []}'
    stderr = ""


class ClaimCase(TranscriptCase):
    """Each test sets CLAIM to the marker it proves."""

    def plugin_dir(self, body, name="p.py"):
        d = os.path.join(self.tmp, "plugins")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w") as f:
            f.write(body)
        os.environ["EOD_SOURCE_DIR"] = d
        ex = load_extract()
        ex.ROOT = self.claude
        ex.CODEX_ROOT = self.codex
        ex.CACHE = os.path.join(self.tmp, "cache")
        return ex

    def tearDown(self):
        os.environ.pop("EOD_SOURCE_DIR", None)
        TranscriptCase.tearDown(self)

    def a_normal_day(self, ex=None):
        ex = ex or self.ex
        self.write_session("-Users-me-work-alpha", "s.jsonl", [
            title_line("Fixed the rounding bug"),
            user_line("my secret prompt about acme corp", DAY),
        ], mtime_date=DAY)
        return ex, ex.build(DAY)


class TestPrivacyClaims(ClaimCase):

    CLAIM_receipt_no_raw_prompts = "receipt-no-raw-prompts"

    def test_receipt_never_prints_raw_prompts(self):
        """README: 'The receipt never prints your raw prompts.'

        The claim is about the receipt, i.e. the card you actually look at. The
        full bill behind 'See full bill' is the verbose view and does show them
        on purpose, which is now stated in the README rather than implied away.
        This gate caught that discrepancy the first time it ran.
        """
        ex, data = self.a_normal_day()
        for surface in (ex.to_html(data), ex.to_text(data)):
            self.assertNotIn("my secret prompt about acme corp", surface)
        # and the full bill genuinely does, so the distinction is real and pinned
        self.assertIn("my secret prompt about acme corp", ex.to_html_full(data))

    CLAIM_polish_sends_prompts = "polish-sends-prompts"

    def test_polish_payload_does_include_prompts(self):
        """README says so explicitly. A documented tradeoff, pinned so it cannot
        widen or silently narrow without the docs moving too."""
        ex, data = self.a_normal_day()
        self.assertIn("my secret prompt about acme corp", ex._polish_input(data))

    CLAIM_polish_no_third_party_names = "polish-no-third-party-names"

    def test_polish_payload_excludes_other_peoples_names(self):
        """README 'Never sent': the names of people you met or worked with."""
        ex = self.ex
        payload = ex._polish_input({
            "date": DAY, "projects": [],
            "meetings": [{"time": "10:00", "title": "Sync", "attendees": "Priya, Sam"}],
            "people": ["Priya Nair", "Sam Okoro"],
        })
        for name in ("Priya", "Sam", "Nair", "Okoro"):
            self.assertNotIn(name, payload)

    CLAIM_polish_off_disables = "polish-off-disables"

    def test_polish_off_stops_the_cli_entirely(self):
        """README: 'EOD then never shells out to the claude CLI.'"""
        ex = self.ex
        calls = []
        ex._claude_bin = lambda: "/fake/claude"
        ex.subprocess = fake_subprocess(calls, FakeRun())
        flag = ex.app_path("polish.off")
        created = not os.path.exists(flag)
        if created:
            open(flag, "w").close()
        try:
            ex.polish({"date": DAY, "projects": [],
                       "commits": [{"repo": "r", "subject": "did some work"}]})
            self.assertEqual(calls, [])
        finally:
            if created:
                os.remove(flag)

    CLAIM_polish_cli_isolated = "polish-cli-isolated"

    def _polish_with_fake_cli(self, results):
        """Run the real polish() against a fake CLI that answers with `results` in
        turn. Returns every argv it was called with."""
        polish_mod = next(m for m in self.ex._mods if m.__name__ == "eod.polish")
        argv = []
        answers = iter(results)

        def run(cmd, **kw):
            argv.append(cmd)
            return next(answers)

        cache = tempfile.mkdtemp(prefix="eod-isolated-")
        try:
            with mock.patch.object(polish_mod, "_claude_bin", lambda: "/fake/claude"), \
                 mock.patch.object(polish_mod, "subprocess", types.SimpleNamespace(run=run)), \
                 mock.patch.object(polish_mod, "CACHE", cache):
                data = {"date": DAY, "projects": [],
                        "commits": [{"repo": "r", "subject": "did some work"}]}
                self.ex.polish(data, force=True)
            log = os.path.join(cache, "polish-error.log")
            self.polish_log = ""
            if os.path.exists(log):
                with open(log) as fh:
                    self.polish_log = fh.read()
        finally:
            shutil.rmtree(cache, ignore_errors=True)
        return argv, data

    def test_polish_runs_the_cli_with_isolation_flags(self):
        """README: no tools, no user settings/hooks/MCP/CLAUDE.md, no saved session."""
        ok = types.SimpleNamespace(returncode=0, stderr="",
                                   stdout='{"highlights": ["a bullet"], "detailed": []}')
        argv, _ = self._polish_with_fake_cli([ok])
        self.assertEqual(len(argv), 1)
        cmd = argv[0]
        self.assertIn("-p", cmd)
        for flag in ("--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(flag, cmd)
        for flag in ("--tools", "--setting-sources"):
            self.assertIn(flag, cmd)
            self.assertEqual(cmd[cmd.index(flag) + 1], "", "%s must be given an empty value" % flag)
        polish_mod = next(m for m in self.ex._mods if m.__name__ == "eod.polish")
        self.assertEqual(polish_mod._claude_env().get("CLAUDE_CODE_DISABLE_CLAUDE_MDS"), "1")

    def test_polish_retries_with_the_old_argv_when_a_flag_is_unknown(self):
        """An older CLI that rejects an isolation flag still produces a summary."""
        rejected = types.SimpleNamespace(returncode=1, stdout="",
                                         stderr="error: unknown option '--no-session-persistence'")
        ok = types.SimpleNamespace(returncode=0, stderr="",
                                   stdout='{"highlights": ["a bullet"], "detailed": []}')
        argv, data = self._polish_with_fake_cli([rejected, ok])
        self.assertEqual(len(argv), 2)
        self.assertIn("--no-session-persistence", argv[0])
        self.assertEqual(argv[1][1:], ["-p", "--output-format", "text"])
        self.assertEqual(data.get("highlights"), ["a bullet"])
        # docs/privacy.md: the retry drops the isolation flags, and says so in the log.
        self.assertIn("retrying without", self.polish_log)

    CLAIM_exclude_hides_projects = "exclude-hides-projects"

    def test_excluded_projects_never_reach_the_receipt(self):
        """README: 'Those projects never reach the receipt.'"""
        self.write_session("-Users-me-work-acme", "s.jsonl", [
            title_line("Confidential acme work"),
            user_line("do the confidential thing", DAY),
        ], mtime_date=DAY)
        key = self.ex.proj_name(os.path.join(self.claude, "-Users-me-work-acme", "s.jsonl"))
        self.ex.EXCLUDE = {key}
        data = self.ex.build(DAY)
        for surface in (self.ex.to_html(data), self.ex.to_text(data),
                        self.ex.to_html_full(data), self.ex.to_text_full(data),
                        self.ex._polish_input(data)):
            self.assertNotIn("acme", surface.lower())

    CLAIM_no_network = "no-network"

    def test_the_engine_makes_no_network_calls(self):
        """README: 'no telemetry', 'nothing leaves your Mac'. The only outbound
        path is the claude CLI subprocess, which polish.off disables. The one
        HTTP client is polish.py's call to Ollama, which is held to loopback at
        runtime by _open_local (tested in test_polish.py)."""
        import ast
        import glob
        from urllib.parse import urlparse
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for path in sorted(glob.glob(os.path.join(root, "eod", "**", "*.py"), recursive=True)):
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            allowed = NETWORK_ALLOWED.get(rel, set())
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), rel)
            for node in ast.walk(tree):
                for mod in _network_imports(node):
                    self.assertIn(mod, allowed, "%s imports %s, an outbound path (line %s)"
                                  % (rel, mod, node.lineno))
        # The one allowed file: exactly one opener, used from exactly one place.
        polish_path = os.path.join(root, "eod", "polish.py")
        with open(polish_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        calls = [n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
                 for n in ast.walk(tree) if isinstance(n, ast.Call)]
        self.assertEqual(calls.count("build_opener"), 1, "polish.py should build one opener")
        self.assertEqual(calls.count("_open_local"), 1, "only _run_ollama should open a URL")
        polish_mod = next(m for m in self.ex._mods if m.__name__ == "eod.polish")
        self.assertEqual(urlparse(polish_mod.OLLAMA_URL).hostname, "127.0.0.1")

    CLAIM_ollama_stays_local = "ollama-stays-local"

    def test_ollama_txt_sends_the_day_to_loopback_and_never_the_cli(self):
        """configuration.md: ollama.txt runs polish on local Ollama instead of the
        claude CLI, only on 127.0.0.1:11434, and a failure falls back like the CLI."""
        from urllib.parse import urlparse
        polish_mod = next(m for m in self.ex._mods if m.__name__ == "eod.polish")
        cli_calls, urls = [], []

        class Resp:
            def __init__(self, body): self.body = body
            def read(self): return self.body
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_open(req, timeout):
            urls.append(req.full_url)
            return Resp(b'{"response": "{\\"highlights\\": [\\"local bullet\\"], \\"detailed\\": []}"}')

        cache = tempfile.mkdtemp(prefix="eod-ollama-claim-")
        try:
            with mock.patch.object(polish_mod, "load_ollama_model", lambda: "llama3.2"), \
                 mock.patch.object(polish_mod, "_claude_bin", lambda: "/fake/claude"), \
                 mock.patch.object(polish_mod, "subprocess", fake_subprocess(cli_calls, FakeRun())), \
                 mock.patch.object(polish_mod, "_open_local", fake_open), \
                 mock.patch.object(polish_mod, "CACHE", cache):
                data = {"date": DAY, "projects": [],
                        "commits": [{"repo": "r", "subject": "did some work"}]}
                self.ex.polish(data, force=True)
        finally:
            shutil.rmtree(cache, ignore_errors=True)
        self.assertEqual(cli_calls, [], "the claude CLI must not run when ollama.txt is set")
        self.assertEqual(data["highlights"], ["local bullet"])
        self.assertEqual(len(urls), 1)
        u = urlparse(urls[0])
        self.assertEqual((u.hostname, u.port), ("127.0.0.1", 11434))


class TestSourceContractClaims(ClaimCase):

    CLAIM_source_failure_visible = "source-failure-visible"

    def test_a_failed_source_is_reported_on_every_daily_surface(self):
        """README: a configured source that fails 'is reported on the receipt'.
        All four surfaces, because the first fix covered only two of them."""
        ex = self.plugin_dir(FAILING)
        _, data = self.a_normal_day(ex)
        for surface in (ex.to_html(data), ex.to_html_full(data),
                        ex.to_text(data), ex.to_text_full(data)):
            self.assertIn("boomsource", surface)

    CLAIM_source_absent_silent = "source-absent-silent"

    def test_an_unavailable_source_says_nothing_anywhere(self):
        """README: 'A source that is not configured says nothing.'"""
        ex = self.plugin_dir(ABSENT)
        _, data = self.a_normal_day(ex)
        self.assertEqual(data["source_problems"], [])
        for surface in (ex.to_html(data), ex.to_html_full(data),
                        ex.to_text(data), ex.to_text_full(data)):
            self.assertNotIn("absentsource", surface)

    CLAIM_plugin_extra_kept = "plugin-extra-kept"

    def test_unknown_keys_are_kept_and_shown(self):
        """README: items under an unknown key 'are kept in data["extra"] rather
        than dropped'. Kept and then never drawn was the earlier half-fix."""
        ex = self.plugin_dir(PLUGIN)
        _, data = self.a_normal_day(ex)
        self.assertEqual(data["extra"].get("linear_issues"), [{"title": "closed ENG-1"}])
        for surface in (ex.to_html(data), ex.to_html_full(data),
                        ex.to_text(data), ex.to_text_full(data)):
            self.assertIn("closed ENG-1", surface)

    CLAIM_broken_plugin_skipped = "broken-plugin-skipped"

    def test_a_broken_plugin_is_reported_and_cannot_stop_the_build(self):
        """README: 'a third-party file cannot stop your receipt building.'"""
        ex = self.plugin_dir(BROKEN, name="broken.py")
        _, data = self.a_normal_day(ex)
        self.assertTrue(data["projects"], "the day must still build")
        self.assertTrue(any("broken.py" in p for p in data["source_problems"]))


class TestWeeklySourceClaims(ClaimCase):
    """The weekly is built from cached days, so it has to read their failures
    back rather than inherit them. It used to not, and could not say so."""

    WEEK = ["2026-10-05", "2026-10-06", "2026-10-07"]

    def cache_day(self, ex, date, highlights, problems=()):
        with open(os.path.join(ex.CACHE, "polish-%s.json" % date), "w") as fh:
            json.dump({"highlights": highlights}, fh)
        with open(os.path.join(ex.CACHE, "%s.json" % date), "w") as fh:
            json.dump({"date": date, "source_problems": list(problems)}, fh)

    def weekly(self, ex):
        ex._claude_bin = lambda: None      # fallback path: no model, no network
        return ex.build_weekly(self.WEEK[-1])

    CLAIM_weekly_source_failure_visible = "weekly-source-failure-visible"

    def test_a_week_with_a_failed_source_says_so_on_both_surfaces(self):
        ex = self.ex
        self.cache_day(ex, self.WEEK[0], ["shipped the parser"])
        self.cache_day(ex, self.WEEK[1], ["fixed the cache"], ["boomsource: token expired"])
        self.cache_day(ex, self.WEEK[2], ["wrote docs"],
                       ["boomsource: HTTP 401", "calendar: no access"])
        data = self.weekly(ex)
        self.assertEqual(data["source_problems"], [
            {"source": "boomsource", "detail": "HTTP 401",
             "days": ["2026-10-06", "2026-10-07"]},
            {"source": "calendar", "detail": "no access", "days": ["2026-10-07"]},
        ])
        text = ex.to_text_weekly(data)
        self.assertIn("! boomsource unavailable on Tue, Wed: HTTP 401", text)
        self.assertIn("! calendar unavailable on Wed: no access", text)
        page = ex.to_html_weekly(data)
        self.assertIn("boomsource unavailable on Tue, Wed: HTTP 401", page)
        self.assertEqual(page.count("<div class='warn'>"), 2)

    def test_a_failure_is_shown_even_when_the_week_has_no_highlights(self):
        ex = self.ex
        self.cache_day(ex, self.WEEK[0], [], ["boomsource: token expired"])
        data = self.weekly(ex)
        self.assertIn("boomsource", ex.to_text_weekly(data))
        self.assertIn("boomsource", ex.to_html_weekly(data))

    def test_a_healthy_week_renders_exactly_as_before(self):
        ex = self.ex
        for d in self.WEEK:
            self.cache_day(ex, d, ["did a thing on " + d])
        data = self.weekly(ex)
        self.assertEqual(data["source_problems"], [])
        legacy = dict(data)
        del legacy["source_problems"]
        self.assertEqual(ex.to_text_weekly(data), ex.to_text_weekly(legacy))
        self.assertEqual(ex.to_html_weekly(data), ex.to_html_weekly(legacy))
        self.assertNotIn("unavailable", ex.to_text_weekly(data))

    def test_a_missing_or_corrupt_day_cache_is_not_a_failure(self):
        ex = self.ex
        self.cache_day(ex, self.WEEK[0], ["shipped"])
        with open(os.path.join(ex.CACHE, "%s.json" % self.WEEK[1]), "w") as fh:
            fh.write("{not json")
        self.assertEqual(self.weekly(ex)["source_problems"], [])


class TestConfigClaims(ClaimCase):

    CLAIM_signature_is_yours = "signature-is-yours"

    def test_signature_is_the_users_and_empties_cleanly(self):
        """README: defaults to your git user.name initials; empty file = no mark."""
        ex = self.ex
        ex.SIG = ""
        _, data = self.a_normal_day(ex)
        html = ex.to_html(data)
        self.assertNotIn("class='sig'", html)
        ex.SIG = "ZQ"
        self.assertIn("ZQ", ex.to_html(ex.build(DAY)))

    CLAIM_repos_txt_read = "repos-txt-read"

    def test_repos_txt_is_actually_consulted(self):
        """README documents it as a way to add repos outside the default roots."""
        import inspect
        self.assertIn("repos.txt", inspect.getsource(self.ex._git_repos))


if __name__ == "__main__":
    unittest.main()
