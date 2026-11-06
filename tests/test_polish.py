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
import types
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


class TestPromptRules(unittest.TestCase):
    """Pin the rules the 2026-10-15 polish test led to (see EVALS.md).

    Rewording a prompt is easy to do in passing. If one of these rules is
    dropped, the overstated "shipped" lines that test found can come back,
    so the wording that carries each rule is pinned here.
    """

    def setUp(self):
        ex = load_extract()
        self.p = next(m for m in ex._mods if m.__name__ == "eod.polish")

    def test_weekly_prompt_never_upgrades_a_daily_line(self):
        w = self.p.WEEKLY_PROMPT
        self.assertIn("Keep 'shipped', 'merged', 'sent' or 'met' wording exactly as a daily line states it", w)
        self.assertIn("Never upgrade a daily line", w)
        self.assertIn("must not become 'Shipped' or 'Merged'", w)

    def test_weekly_prompt_adds_nothing(self):
        w = self.p.WEEKLY_PROMPT
        self.assertIn("Never add people, teams, meetings, recipients or cadence words", w)
        self.assertIn("'Worked with <name>' only when the input shows that person working on it", w)

    def test_weekly_outcome_comes_from_the_dailies(self):
        w = self.p.WEEKLY_PROMPT
        self.assertIn("show the outcome the dailies state", w)
        # The old line offered 'shipped' and 'merged' as examples of an outcome to show.
        self.assertNotIn("outcome (e.g. 'shipped', 'merged')", w)

    def test_daily_prompt_keeps_the_outcome_and_no_additions_rules(self):
        d = self.p.POLISH_PROMPT
        self.assertIn("Only say shipped, merged, deployed, released, sent, shared or met when the input shows it", d)
        self.assertIn("A commit alone is 'fixed' or 'committed', not 'shipped'", d)
        self.assertIn("is not proof it was sent", d)
        self.assertIn("Never add people, teams, meetings, recipients or cadence words", d)


class FakeResp:
    """What _open_local hands back: a context manager with read()."""

    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def ollama_reply(text):
    return FakeResp(json.dumps({"model": "llama3.2", "response": text, "done": True}).encode())


class TestOllamaProvider(unittest.TestCase):
    """ollama.txt swaps the claude CLI for a local model. The HTTP call is faked;
    the harness already makes a real one fail loudly."""

    def setUp(self):
        self.ex = load_extract()
        self.p = next(m for m in self.ex._mods if m.__name__ == "eod.polish")
        self.tmp = tempfile.mkdtemp(prefix="eod-ollama-")
        self.ex.CACHE = self.tmp
        self.cli_calls = []
        self.ex._claude_bin = lambda: "/fake/claude"
        self.ex.subprocess = fake_subprocess(self.cli_calls, FakeRun())
        self.ex.load_ollama_model = lambda: "qwen2.5:7b"
        self.requests = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _serve(self, answer):
        """answer: a FakeResp to return, or an exception to raise."""
        def fake_open(req, timeout):
            self.requests.append((req, timeout))
            if isinstance(answer, BaseException):
                raise answer
            return answer
        self.ex._open_local = fake_open

    def _day(self):
        return {"date": "2026-08-06", "projects": [],
                "commits": [{"repo": "r", "subject": "some work happened"}]}

    def _log(self):
        p = os.path.join(self.tmp, "polish-error.log")
        if not os.path.exists(p):
            return ""
        with open(p) as fh:
            return fh.read()

    def test_success_uses_ollama_and_the_shared_parser(self):
        # Prose around the object, as a small model sometimes adds: the same
        # extraction path as the CLI's output must strip it.
        self._serve(ollama_reply('Sure! {"highlights": ["  local bullet  "], '
                                 '"detailed": [{"area": "A", "items": ["x", ""]}]} done'))
        d = self._day()
        self.ex.polish(d)
        self.assertEqual(self.cli_calls, [], "claude CLI must not run in Ollama mode")
        self.assertEqual(d["highlights"], ["local bullet"])
        self.assertEqual(d["detailed"], [{"area": "A", "items": ["x"]}])
        req, timeout = self.requests[0]
        self.assertEqual(req.full_url, "http://127.0.0.1:11434/api/generate")
        self.assertEqual(timeout, self.p.OLLAMA_TIMEOUT)
        body = json.loads(req.data.decode())
        self.assertEqual(body["model"], "qwen2.5:7b")
        self.assertIs(body["stream"], False)
        self.assertTrue(body["prompt"].startswith(self.p.POLISH_PROMPT))
        self.assertIn("some work happened", body["prompt"])
        with open(os.path.join(self.tmp, "polish-2026-08-06.json")) as fh:
            self.assertEqual(json.load(fh)["highlights"], ["local bullet"])

    def test_connection_refused_falls_back_and_logs(self):
        import urllib.error
        self._serve(urllib.error.URLError(ConnectionRefusedError(61, "Connection refused")))
        d = self._day()
        self.ex.polish(d)
        self.assertNotIn("highlights", d)
        self.assertEqual(self.cli_calls, [], "a dead Ollama must not fall through to the cloud")
        self.assertIn("ollama not reachable", self._log())

    def test_connection_refused_keeps_the_last_good_summary(self):
        import urllib.error
        p = os.path.join(self.tmp, "polish-2026-08-06.json")
        with open(p, "w") as f:
            json.dump({"key": "stale", "highlights": ["kept"], "detailed": []}, f)
        self._serve(urllib.error.URLError(ConnectionRefusedError(61, "Connection refused")))
        d = self._day()
        self.ex.polish(d, force=True)
        self.assertEqual(d["highlights"], ["kept"])

    def test_missing_model_is_logged_with_ollamas_reason(self):
        import io, urllib.error
        err = urllib.error.HTTPError(self.p.OLLAMA_URL, 404, "Not Found", {},
                                     io.BytesIO(b'{"error":"model \'qwen2.5:7b\' not found"}'))
        self._serve(err)
        d = self._day()
        self.ex.polish(d)
        self.assertNotIn("highlights", d)
        self.assertIn("404", self._log())
        self.assertIn("not found", self._log())

    def test_malformed_http_body_falls_back(self):
        self._serve(FakeResp(b"<html>not json</html>"))
        d = self._day()
        self.ex.polish(d)
        self.assertNotIn("highlights", d)
        self.assertIn("not JSON", self._log())

    def test_reply_without_response_text_falls_back(self):
        self._serve(FakeResp(b'{"error": "something odd"}'))
        d = self._day()
        self.ex.polish(d)
        self.assertNotIn("highlights", d)
        self.assertIn("no response text", self._log())

    def test_model_text_that_is_not_the_object_falls_back(self):
        self._serve(ollama_reply("I could not do that."))
        d = self._day()
        self.ex.polish(d)
        self.assertNotIn("highlights", d)
        self.assertTrue(self._log())

    def test_weekly_uses_ollama_and_falls_back_by_day(self):
        self._serve(ollama_reply('{"highlights": ["week line"], "detailed": []}'))
        w = {"week_start": "2026-08-03", "days": [("2026-08-04", ["mon thing"])]}
        self.ex.polish_weekly(w)
        self.assertEqual(w["highlights"], ["week line"])
        self.assertEqual(self.cli_calls, [])
        self.assertTrue(json.loads(self.requests[0][0].data.decode())["prompt"]
                        .startswith(self.p.WEEKLY_PROMPT))

        import urllib.error
        self._serve(urllib.error.URLError("refused"))
        w = {"week_start": "2026-08-10", "days": [("2026-08-11", ["tue thing"])]}
        self.ex.polish_weekly(w)
        self.assertEqual(w["highlights"], ["tue thing"])

    def test_polish_off_beats_ollama_txt(self):
        flag = os.path.join(os.path.dirname(EXTRACT), "polish.off")
        created = not os.path.exists(flag)
        open(flag, "a").close()
        try:
            d = self._day()
            self.ex.polish(d)
            self.assertEqual(self.requests, [])
            self.assertNotIn("highlights", d)
        finally:
            if created:
                os.remove(flag)


class TestProviderChoice(unittest.TestCase):
    """The default stays the claude CLI, and ollama.txt is read the documented way."""

    def setUp(self):
        self.ex = load_extract()
        self.cfg = next(m for m in self.ex._mods if m.__name__ == "eod.config")
        self.tmp = tempfile.mkdtemp(prefix="eod-provider-")
        self.cfg.APP_DIR = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, text):
        with open(os.path.join(self.tmp, "ollama.txt"), "w") as f:
            f.write(text)

    def test_no_file_means_claude(self):
        self.assertIsNone(self.cfg.load_ollama_model())

    def test_empty_file_means_the_default_model(self):
        self._write("")
        self.assertEqual(self.cfg.load_ollama_model(), self.cfg.OLLAMA_DEFAULT_MODEL)

    def test_first_line_names_the_model(self):
        self._write("  qwen2.5:7b  \nignored\n")
        self.assertEqual(self.cfg.load_ollama_model(), "qwen2.5:7b")

    def test_default_provider_is_byte_identical_claude(self):
        """No ollama.txt: the CLI gets exactly the argv and prompt it always got,
        and no HTTP call is attempted (the harness stub would raise if one were)."""
        p = next(m for m in self.ex._mods if m.__name__ == "eod.polish")
        self.ex.CACHE = self.tmp
        self.ex.load_ollama_model = self.cfg.load_ollama_model   # the real reader, no file present
        seen = []

        def run(cmd, **kw):
            seen.append((cmd, kw))
            return FakeRun()
        self.ex._claude_bin = lambda: "/fake/claude"
        self.ex.subprocess = types.SimpleNamespace(run=run)
        d = {"date": "2026-08-06", "projects": [],
             "commits": [{"repo": "r", "subject": "some work happened"}]}
        self.ex.polish(d)
        self.assertEqual(len(seen), 1)
        cmd, kw = seen[0]
        self.assertEqual(cmd, ["/fake/claude"] + p.CLAUDE_ARGS)
        self.assertEqual(kw["input"], p.POLISH_PROMPT + "\n\n" + p._polish_input(d))
        self.assertEqual(kw["timeout"], 150)
        self.assertEqual(d["highlights"], ["a fresh bullet"])


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
