"""Every behavioural promise the README makes, as an executable test.

Three times in one session the README described behaviour the code did not have:
the polish payload, source failures appearing on the receipt, and then the
half-fix of that same thing. Each time the sentence was written before the last
mile of the code, and twice it took someone else to notice.

Remembering not to do that is not a fix. This is: each claim in README.md carries
a `<!--claim:NAME-->` marker, each test here declares the claim it proves, and
tests/test_claim_coverage.py fails the build if the two sets ever diverge. You
cannot add a promise to the README without also making it falsifiable, and you
cannot quietly drop the behaviour without a red test.

Add a claim => add a test here. Delete a claim => delete its test.
"""

import os
import unittest

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
        path is the claude CLI subprocess, which polish.off disables."""
        import glob
        src = ""
        for p in glob.glob(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eod", "**", "*.py"),
                recursive=True):
            with open(p) as f:
                src += f.read()
        for banned in ("import requests", "import urllib.request", "urlopen(",
                       "http.client", "import socket"):
            self.assertNotIn(banned, src, "%s would be an outbound path" % banned)


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
