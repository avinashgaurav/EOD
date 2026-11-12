"""Features built on the receipts (audit B1, B3 to B11, B13, B14)."""

import json, os, subprocess, sys, tempfile, unittest

from harness import load_extract

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def mod(ex, name):
    return next(m for m in ex._mods if m.__name__ == name)


class FeatureCase(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()
        self.f = mod(self.ex, "eod.features")
        self.cfg = mod(self.ex, "eod.config")
        self.tmp = tempfile.mkdtemp()
        self.cache = os.path.join(self.tmp, "cache")
        os.makedirs(self.cache)
        self.cfg.APP_DIR = self.tmp
        self.f.CACHE = self.cache

    def day(self, date, lines, **extra):
        with open(os.path.join(self.cache, "polish-%s.json" % date), "w") as fh:
            json.dump({"highlights": lines}, fh)
        with open(os.path.join(self.cache, "%s.json" % date), "w") as fh:
            json.dump(dict({"date": date}, **extra), fh)


class TestRedaction(FeatureCase):
    def test_secrets_emails_hosts_and_paths(self):
        r = self.f.redact("key sk-abcdefghijklmnopqrst1234 to sam@acme.com on db.corp in /Users/ana/x "
                          "ghp_abcdefghijklmn12 https://hooks.slack.com/services/T/B/C")
        for leak in ("sk-abc", "sam@acme.com", "db.corp", "/Users/ana", "ghp_", "hooks.slack.com"):
            self.assertNotIn(leak, r)

    def test_can_be_switched_off(self):
        open(os.path.join(self.tmp, "redact.off"), "w").close()
        self.assertEqual(self.f.redact("sam@acme.com"), "sam@acme.com")

    def test_the_ai_payload_is_redacted(self):
        p = mod(self.ex, "eod.polish")
        d = {"projects": [{"name": "x", "sessions": [{"title": "Mail sam@acme.com", "prompts": []}]}]}
        self.assertNotIn("sam@acme.com", p._polish_input(d))


class TestMorningSearchPlanBrag(FeatureCase):
    def test_morning_standup_uses_yesterday_today_and_open_prs(self):
        self.day("2026-11-12", ["Fixed the parser."], prs=[{"number": 7, "title": "Parser", "state": "OPEN"}])
        self.day("2026-11-13", [], meetings=[{"time": "10:00", "title": "Design review"}])
        t = self.f.morning_standup("2026-11-13")
        self.assertIn("Fixed the parser.", t)
        self.assertIn("10:00 Design review", t)
        self.assertIn("PR #7", t)
        self.assertIn("Blockers", t)

    def test_morning_skips_the_weekend(self):
        self.assertEqual(self.f.previous_workday("2026-11-16"), "2026-11-13")

    def test_search_needs_every_word(self):
        self.day("2026-11-10", ["Fixed webhook retries.", "Wrote docs."])
        self.day("2026-11-11", ["Webhook dashboard."])
        self.assertEqual(self.f.search("webhook retries"), [("2026-11-10", "Fixed webhook retries.")])
        self.assertEqual(len(self.f.search("webhook")), 2)

    def test_plan_marks_done_by_overlap(self):
        self.f.save_plan("2026-11-12", "Fix coupon rounding\nWrite onboarding copy\n")
        st = dict(self.f.plan_status("2026-11-12", ["Fixed the coupon rounding bug (#412)."]))
        self.assertEqual(st["Fix coupon rounding"], "done")
        self.assertEqual(st["Write onboarding copy"], "open")

    def test_brag_without_ai_lists_the_days(self):
        self.day("2026-10-01", ["Shipped v2."])
        self.day("2026-10-02", ["Fixed sso."])
        doc = self.f.brag_doc("2026-10-01", "2026-10-31")
        self.assertIn("Shipped v2.", doc)
        self.assertIn("Fixed sso.", doc)
        self.assertIsNone(self.f.brag_doc("2025-01-01", "2025-01-31"))

    def test_brag_redacts_before_the_ai(self):
        self.day("2026-10-01", ["Mailed sam@acme.com the plan."])
        seen = []
        self.f.brag_doc("2026-10-01", "2026-10-31", lambda p: seen.append(p) or "## Theme\n- x")
        self.assertNotIn("sam@acme.com", seen[0])


class TestInsightAndHistory(FeatureCase):
    def test_insight_is_off_by_default(self):
        self.assertIsNone(self.f.daily_insight({"date": "2026-11-12", "apps": [{"name": "Code", "secs": 600}]}))
        open(os.path.join(self.tmp, "insight.on"), "w").close()
        self.assertIn("Code", self.f.daily_insight({"date": "2026-11-12", "apps": [{"name": "Code", "secs": 600}]}))

    def test_history_month_marks_days(self):
        self.day("2026-11-03", ["A."])
        with open(os.path.join(self.cache, "sent-days.json"), "w") as fh:
            json.dump(["2026-11-03"], fh)
        page = self.f.history_month_html("2026-11", "")
        self.assertIn("class='has sent'", page)
        self.assertIn("goDate',date:'2026-11-03'", page)
        self.assertIn("November 2026", page)


class TestSendPresets(unittest.TestCase):
    def test_email_and_format_parse(self):
        cfg = mod(load_extract(), "eod.config")
        os.environ["EOD_SEND_TARGETS"] = "email boss@example.com\nteams https://x.example/w format=markdown\nslack https://h format=fancy"
        try:
            t = cfg.load_send_targets()
        finally:
            os.environ.pop("EOD_SEND_TARGETS", None)
        self.assertEqual(t[0], {"kind": "email", "to": "boss@example.com", "format": None})
        self.assertEqual(t[1]["format"], "markdown")
        self.assertEqual(t[2], {"kind": None, "bad": 3})


class TestReviewFixes(FeatureCase):
    def test_work_shows_once_with_highlights_and_with_a_plan(self):
        h = mod(self.ex, "eod.render.html")
        with open(os.path.join(HERE, "snapshots", "day.json")) as fh:
            d = json.load(fh)
        page = h.to_html(dict(d, highlights=["Fixed it."]))
        self.assertIn("<section class='work'", page)
        self.assertNotIn("<div class='sect'>WORK</div>", page)
        self.f.save_plan(d["date"], "Fix it")
        page = h.to_html(dict(d, highlights=["Fixed it."]))
        self.assertNotIn("<div class='sect'>WORK</div>", page)
        self.assertIn(">PLANNED<", page)
        page = h.to_html(dict(d))                       # no highlights: the per-project fallback still shows
        self.assertIn("<div class='sect'>WORK</div>", page)

    def test_hide_rules_reach_morning_brag_search_and_ask(self):
        mod(self.ex, "eod.hide").add_hide_rule("line", "dentist", os.path.join(self.tmp, "hide.txt"))
        self.day("2026-11-12", ["Fixed the parser.", "Booked the dentist."])
        self.day("2026-11-13", [])
        self.assertNotIn("dentist", self.f.morning_standup("2026-11-13"))
        self.assertNotIn("dentist", self.f.brag_doc("2026-11-01", "2026-11-30"))
        self.assertEqual(self.f.search("dentist"), [])
        self.assertNotIn("dentist", self.f.ask("when the dentist", lambda p: None))

    def test_ask_falls_back_when_ai_gives_nothing_or_fails(self):
        self.day("2026-11-12", ["Fixed webhook retries."])
        self.assertIn("matching lines", self.f.ask("webhook retries", lambda p: None))
        def boom(p):
            raise RuntimeError("ollama down")
        self.assertIn("matching lines", self.f.ask("webhook retries", boom))

    def test_redaction_leaves_versions_and_packages_alone(self):
        self.assertEqual(self.f.redact("Bumped v1.2.local and pkg@1.2.3"), "Bumped v1.2.local and pkg@1.2.3")
        self.assertEqual(self.f.redact("Called db.corp"), "Called [host]")

    def test_bad_month_is_refused(self):
        with self.assertRaises(ValueError):
            self.f.history_month_html("2026-13", "")

    def test_week_share_card_is_labelled(self):
        h = mod(self.ex, "eod.render.html")
        page = h.to_html_share_week({"week_start": "2026-11-09", "week_end": "2026-11-13", "highlights": ["A."],
                                     "report": {"tldr": "Shipped A."}})
        self.assertIn("WEEK IN A RECEIPT", page)
        self.assertIn("Shipped A.", page)

    def test_ollama_free_text_has_no_json_format(self):
        p = mod(self.ex, "eod.polish")
        sent = []
        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps({"response": "text"}).encode()
        p._open_local = lambda req, timeout: (sent.append(json.loads(req.data)), R())[1]
        p._run_ollama("m", "hello", raw=True)
        p._run_ollama("m", "hello")
        self.assertNotIn("format", sent[0])
        self.assertEqual(sent[1]["format"], "json")


class TestTimeline(unittest.TestCase):
    def test_sessions_and_meetings_drawn(self):
        h = mod(load_extract(), "eod.render.html")
        svg = h.timeline_svg({"projects": [{"name": "eod", "sessions": [{"start": "09:12", "end": "09:40", "title": "Fix <x>"}]}],
                              "meetings": [{"time": "11:00", "title": "Standup"}]})
        self.assertIn("var(--carbon)", svg)
        self.assertIn("var(--accent)", svg)
        self.assertIn("Fix &lt;x&gt;", svg)
        self.assertEqual(h.timeline_svg({"projects": [], "meetings": []}), "")


class TestMcpServer(unittest.TestCase):
    def test_lists_tools_and_answers(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "eod_day", "arguments": {"date": "bad"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "nope"}]
        r = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "eod-mcp")], input="\n".join(map(json.dumps, msgs)),
                           capture_output=True, text=True, timeout=30)
        out = [json.loads(l) for l in r.stdout.splitlines()]
        self.assertEqual([m["id"] for m in out], [1, 2, 3, 4])            # no reply to the notification
        self.assertEqual(out[0]["result"]["protocolVersion"], "2025-06-18")
        names = [t["name"] for t in out[1]["result"]["tools"]]
        self.assertEqual(names, ["eod_day", "eod_week", "eod_standup", "eod_search"])
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in out[1]["result"]["tools"]))
        self.assertTrue(out[2]["result"]["isError"])
        self.assertEqual(out[3]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
