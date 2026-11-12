"""Trust and privacy defaults (audit F01, F05, F07, F08, F09)."""

import json, os, tempfile, unittest

from harness import load_extract

HERE = os.path.dirname(os.path.abspath(__file__))


def mod(ex, name):
    return next(m for m in ex._mods if m.__name__ == name)


class TestHideRules(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()
        self.hide = mod(self.ex, "eod.hide")
        self.path = os.path.join(tempfile.mkdtemp(), "hide.txt")

    def day(self):
        return {"apps": [{"name": "Messages", "secs": 60}, {"name": "Code", "secs": 600}],
                "web": [{"host": "news.example.com", "count": 3}, {"host": "github.com", "count": 9}],
                "projects": [{"name": "eod", "sessions": [{"title": "Fix the parser"}, {"title": "Book the dentist"}]}],
                "highlights": ["Fixed the parser.", "Booked the dentist."],
                "detailed": [{"area": "Misc", "items": ["Booked the dentist."]}],
                "commits": [{"subject": "dentist notes"}, {"subject": "parser fix"}], "docs": []}

    def test_rules_round_trip_and_dedupe(self):
        self.assertTrue(self.hide.add_hide_rule("site", "News.Example.com", self.path))
        self.assertTrue(self.hide.add_hide_rule("site", "news.example.com", self.path))
        self.assertFalse(self.hide.add_hide_rule("folder", "x", self.path))
        self.assertFalse(self.hide.add_hide_rule("line", "   ", self.path))
        self.assertEqual(self.hide.load_hide_rules(self.path)["site"], ["news.example.com"])

    def test_hidden_things_leave_every_part_of_the_day(self):
        for k, v in (("app", "messages"), ("site", "news.example.com"), ("line", "dentist")):
            self.hide.add_hide_rule(k, v, self.path)
        d = self.hide.apply_hide(self.day(), self.hide.load_hide_rules(self.path))
        self.assertEqual([a["name"] for a in d["apps"]], ["Code"])
        self.assertEqual([w["host"] for w in d["web"]], ["github.com"])
        self.assertEqual([s["title"] for s in d["projects"][0]["sessions"]], ["Fix the parser"])
        self.assertEqual(d["highlights"], ["Fixed the parser."])
        self.assertEqual(d["detailed"], [])
        self.assertEqual([c["subject"] for c in d["commits"]], ["parser fix"])

    def test_no_rules_changes_nothing(self):
        d = self.day()
        self.assertEqual(self.hide.apply_hide(d, {"line": [], "site": [], "app": []}), self.day())


class TestSendTargetsFromEnv(unittest.TestCase):
    def test_env_wins_over_the_file(self):
        cfg = mod(load_extract(), "eod.config")
        os.environ["EOD_SEND_TARGETS"] = "slack https://hooks.slack.com/services/T/B/x\nnonsense\n# note"
        try:
            t = cfg.load_send_targets()
        finally:
            os.environ.pop("EOD_SEND_TARGETS", None)
        self.assertEqual(t[0], {"kind": "slack", "url": "https://hooks.slack.com/services/T/B/x"})
        self.assertEqual(t[1], {"kind": None, "bad": 2})
        self.assertEqual(len(t), 2)


class TestCopyDefaults(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()
        with open(os.path.join(HERE, "snapshots", "day.json")) as fh:
            self.day = json.load(fh)

    def test_primary_copy_is_work_only(self):
        d = json.loads(json.dumps(self.day))
        d["highlights"] = ["Fixed the parser."]
        d["apps"] = [{"name": "Messages", "secs": 900}]
        page = self.ex.to_html(d)
        upd = page.split("id='updText' style='display:none'>", 1)[1].split("</div>", 1)[0]
        self.assertIn("Fixed the parser.", upd)
        self.assertNotIn("Messages", upd)
        self.assertIn("Copy update", page)

    def test_send_needs_a_preview_not_a_double_press(self):
        page = self.ex.to_html(dict(self.day, highlights=["Fixed it."]), send_to=["Slack"])
        self.assertIn("Send preview", page)
        self.assertNotIn("Sure?", page)
        self.assertIn("id='sendTo' style='display:none'>Slack<", page)

    def test_weekly_app_hours_are_off_in_copy_by_default(self):
        w = {"week_start": "2026-11-09", "week_end": "2026-11-13", "generated_at": "2026-11-13 18:05:00",
             "source_problems": [], "highlights": ["A."], "report": {"blockers": []}, "detailed": [],
             "time": {"days": [{"date": "2026-11-09", "secs": 3600}], "total": 3600,
                      "top_apps": [{"name": "Chrome", "secs": 3600}]}, "tickets": {}}
        page = self.ex.to_html_weekly(w)
        self.assertRegex(page, r"data-title='Time by app'><div class='depthead'>.*?<input type='checkbox' id='inc\d+'>")
        self.assertRegex(page, r"data-title='Time spent'>.*?<input type='checkbox' id='inc\d+' checked>")


if __name__ == "__main__":
    unittest.main()


class TestSecretsNeverReachChildren(unittest.TestCase):
    def test_send_targets_are_removed_from_child_env(self):
        os.environ["EOD_SEND_TARGETS"] = "slack https://hooks.slack.com/services/T/B/secret"
        try:
            cfg = mod(load_extract(), "eod.config")
            self.assertNotIn("EOD_SEND_TARGETS", os.environ)          # popped at engine start
            self.assertNotIn("EOD_SEND_TARGETS", cfg._full_env())     # and never handed to a child
            self.assertEqual(cfg.load_send_targets()[0]["kind"], "slack")  # still usable for --send
        finally:
            os.environ.pop("EOD_SEND_TARGETS", None)

    def test_labels_come_from_names_only(self):
        os.environ["EOD_SEND_LABELS"] = "Slack,Linear"
        try:
            cfg = mod(load_extract(), "eod.config")
            self.assertEqual(cfg.send_labels(), ["Slack", "Linear"])
        finally:
            os.environ.pop("EOD_SEND_LABELS", None)


class TestHideEverywhere(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()
        self.cfg = mod(self.ex, "eod.config")
        self.tmp = tempfile.mkdtemp()
        self.cfg.APP_DIR = self.tmp
        hide = mod(self.ex, "eod.hide")
        hide.add_hide_rule("line", "dentist", os.path.join(self.tmp, "hide.txt"))
        self.hide = hide

    def test_send_and_its_preview_agree(self):
        send = mod(self.ex, "eod.send")
        send.CACHE = self.tmp
        with open(os.path.join(self.tmp, "2026-11-10.json"), "w") as fh:
            json.dump({"date": "2026-11-10", "projects": [], "highlights": ["Fixed the parser.", "Booked the dentist."]}, fh)
        d = send.card_data("2026-11-10", lambda _d: {})
        self.assertEqual(d["highlights"], ["Fixed the parser."])

    def test_weekly_never_sees_hidden_lines(self):
        self.assertEqual(self.hide.hide_lines(["Fixed it.", "Dentist at 4."]), ["Fixed it."])

    def test_meetings_prs_prompts_and_page_titles(self):
        d = {"projects": [{"name": "p", "sessions": [{"title": "Work", "prompts": [{"text": "call the dentist"}, {"text": "fix"}]}]}],
             "meetings": [{"title": "Dentist"}, {"title": "Standup"}], "prs": [{"title": "dentist bot"}],
             "web": [{"host": "x.com", "titles": [{"title": "dentist near me"}, {"title": "docs"}]}]}
        self.hide.apply_hide(d)
        self.assertEqual([p["text"] for p in d["projects"][0]["sessions"][0]["prompts"]], ["fix"])
        self.assertEqual([m["title"] for m in d["meetings"]], ["Standup"])
        self.assertEqual(d["prs"], [])
        self.assertEqual([t["title"] for t in d["web"][0]["titles"]], ["docs"])
