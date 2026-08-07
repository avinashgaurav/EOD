"""The AI-polish step: what it sends, and how often it runs.

This is the only part of EOD that leaves the machine, so the payload assertions
here are the executable form of the privacy claim in the README. If someone later
widens the payload, one of these should fail.

The CLI is faked throughout. No test in this file can spawn a subprocess or spend
a token; the harness already sets _claude_bin to None, and each suite that wants a
"working" CLI replaces subprocess.run with a recorder.
"""

import json
import os
import shutil
import tempfile
import time
import unittest

from harness import EXTRACT, fake_subprocess, load_extract


class FakeRun:
    returncode = 0
    stdout = '{"highlights": ["a fresh bullet"], "detailed": []}'
    stderr = ""


class TestPayloadPrivacy(unittest.TestCase):
    """Exactly what crosses the boundary."""

    def setUp(self):
        self.ex = load_extract()

    def _payload(self, **over):
        data = {
            "date": "2026-08-06",
            "projects": [{"name": "alpha", "sessions": [
                {"title": "Fix the parser",
                 "prompts": [{"t": "09:00", "text": "a real prompt here"}]}]}],
            "commits": [{"repo": "eod", "subject": "Fix the parser"}],
            "meetings": [{"time": "10:00", "title": "Roadmap sync", "attendees": "Priya, Sam"}],
            "people": ["Priya Nair", "Sam Okoro"],
            "docs": [{"name": "deck.pptx", "folder": "Desktop"}],
            "web": [{"host": "docs.python.org", "titles": [{"title": "re module"}]}],
        }
        data.update(over)
        return self.ex._polish_input(data)

    def test_collaborator_names_never_leave(self):
        """Other people never agreed to this, so their names stay on the machine."""
        out = self._payload()
        for name in ("Priya", "Sam", "Nair", "Okoro"):
            self.assertNotIn(name, out, "%s leaked into the polish payload" % name)

    def test_meeting_titles_still_go(self):
        self.assertIn("Roadmap sync", self._payload())

    def test_prompts_do_go_and_the_readme_says_so(self):
        """Not a leak, a documented tradeoff. Pinned so it cannot change quietly."""
        self.assertIn("a real prompt here", self._payload())

    def test_mail_and_chat_hosts_are_skipped(self):
        out = self._payload(web=[
            {"host": "mail.google.com", "titles": [{"title": "Inbox (312)"}]},
            {"host": "docs.python.org", "titles": [{"title": "re module"}]},
        ])
        self.assertNotIn("Inbox", out)
        self.assertIn("re module", out)

    def test_payload_is_stable_for_identical_input(self):
        """The cache key hashes this text; instability would defeat the whole cache."""
        self.assertEqual(self._payload(), self._payload())


class TestDebounce(unittest.TestCase):
    """eod.lua runs the engine every 10 minutes all day. Each real polish is a ~40s
    subprocess plus tokens, so the floor between automatic runs is load-bearing."""

    def setUp(self):
        self.ex = load_extract()
        self.tmp = tempfile.mkdtemp(prefix="eod-polish-")
        self.ex.CACHE = self.tmp
        self.calls = []
        self.ex._claude_bin = lambda: "/fake/claude"
        self.ex.subprocess = fake_subprocess(self.calls, FakeRun())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _day(self, n):
        return {"date": "2026-08-%02d" % n, "projects": [],
                "commits": [{"repo": "r", "subject": "subject number %d" % n}]}

    def _seed_cache(self, data, age_seconds):
        p = os.path.join(self.tmp, "polish-" + data["date"] + ".json")
        with open(p, "w") as f:
            json.dump({"key": "A-STALE-KEY",
                       "highlights": ["the cached bullet"], "detailed": []}, f)
        t = time.time() - age_seconds
        os.utime(p, (t, t))

    def test_first_build_of_a_day_polishes_immediately(self):
        d = self._day(1)
        self.ex.polish(d)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(d["highlights"], ["a fresh bullet"])

    def test_recent_summary_is_reused_even_when_work_changed(self):
        d = self._day(2)
        self._seed_cache(d, age_seconds=60)
        self.ex.polish(d)
        self.assertEqual(self.calls, [], "should not have called the CLI")
        self.assertEqual(d["highlights"], ["the cached bullet"])

    def test_stale_summary_is_refreshed(self):
        d = self._day(3)
        self._seed_cache(d, age_seconds=self.ex.POLISH_MIN_INTERVAL + 60)
        self.ex.polish(d)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(d["highlights"], ["a fresh bullet"])

    def test_regenerate_button_ignores_the_floor(self):
        d = self._day(4)
        self._seed_cache(d, age_seconds=10)
        self.ex.polish(d, force=True)
        self.assertEqual(len(self.calls), 1)

    def test_unchanged_work_never_calls_the_cli(self):
        """The pre-existing hash cache, which the debounce sits on top of."""
        d = self._day(5)
        self.ex.polish(d)
        self.assertEqual(len(self.calls), 1)
        again = self._day(5)
        os.utime(os.path.join(self.tmp, "polish-" + d["date"] + ".json"),
                 (time.time() - self.ex.POLISH_MIN_INTERVAL - 60,) * 2)
        self.ex.polish(again)
        self.assertEqual(len(self.calls), 1, "identical work should reuse the summary")

    def test_hand_edits_are_never_overwritten(self):
        d = self._day(6)
        p = os.path.join(self.tmp, "polish-" + d["date"] + ".json")
        with open(p, "w") as f:
            json.dump({"key": "whatever", "edited": True,
                       "highlights": ["what the human wrote"], "detailed": []}, f)
        self.ex.polish(d)
        self.assertEqual(self.calls, [])
        self.assertEqual(d["highlights"], ["what the human wrote"])
        self.assertTrue(d.get("edited"))


class TestPolishOff(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()
        self.calls = []
        self.ex._claude_bin = lambda: "/fake/claude"
        self.ex.subprocess = fake_subprocess(self.calls, FakeRun())
        self.flag = os.path.join(os.path.dirname(EXTRACT), "polish.off")
        self.created = not os.path.exists(self.flag)

    def tearDown(self):
        if self.created and os.path.exists(self.flag):
            os.remove(self.flag)

    def test_polish_off_disables_the_step_entirely(self):
        open(self.flag, "w").close()
        d = {"date": "2026-08-06", "projects": [],
             "commits": [{"repo": "r", "subject": "some work happened"}]}
        self.ex.polish(d)
        self.assertEqual(self.calls, [])
        self.assertNotIn("highlights", d)


class TestNoCli(unittest.TestCase):
    def test_missing_cli_falls_back_quietly_and_logs(self):
        ex = load_extract()                      # harness leaves _claude_bin as None
        ex.CACHE = tempfile.mkdtemp(prefix="eod-nocli-")
        try:
            d = {"date": "2026-08-06", "projects": [],
                 "commits": [{"repo": "r", "subject": "some work happened"}]}
            ex.polish(d)
            self.assertNotIn("highlights", d)
            log = os.path.join(ex.CACHE, "polish-error.log")
            self.assertTrue(os.path.exists(log), "the reason should be recorded")
            with open(log) as fh:
                self.assertIn("no claude CLI", fh.read())
        finally:
            shutil.rmtree(ex.CACHE, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
