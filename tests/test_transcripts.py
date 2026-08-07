"""build(): the core parse. Titles, grouping, dedup, date filtering, exclusion."""

import os
import unittest

from harness import TranscriptCase, title_line, user_line

DAY = "2026-08-06"
OTHER = "2026-08-05"


class TestTitles(TranscriptCase):
    def test_uses_the_session_title(self):
        self.write_session("-Users-me-work-alpha", "s1.jsonl", [
            title_line("Fix the checkout rounding bug"),
            user_line("please look at checkout", DAY),
        ], mtime_date=DAY)
        data = self.ex.build(DAY)
        self.assertEqual(len(data["projects"]), 1)
        self.assertEqual(data["projects"][0]["sessions"][0]["title"],
                         "Fix the checkout rounding bug")

    def test_accepts_both_title_spellings(self):
        """Claude Code renamed ai-title -> custom-title once already and it blanked
        every WORK line for four days. Both spellings must keep working."""
        for i, key in enumerate(("ai-title", "custom-title")):
            self.write_session("-Users-me-work-alpha", "s%d.jsonl" % i, [
                title_line("Title via %s" % key, key=key),
                user_line("handle the %s case" % key, DAY),
            ], mtime_date=DAY)
        titles = {s["title"] for s in self.ex.build(DAY)["projects"][0]["sessions"]}
        self.assertEqual(titles, {"Title via ai-title", "Title via custom-title"})

    def test_falls_back_to_first_prompt_when_untitled(self):
        self.write_session("-Users-me-work-alpha", "s1.jsonl", [
            user_line("investigate the flaky webhook test", DAY),
        ], mtime_date=DAY)
        s = self.ex.build(DAY)["projects"][0]["sessions"][0]
        self.assertTrue(s["title"].startswith("investigate the flaky webhook"))

    def test_untitled_sessions_are_counted(self):
        self.write_session("-Users-me-work-alpha", "titled.jsonl",
                           [title_line("Has a title"), user_line("look at the parser", DAY)], mtime_date=DAY)
        self.write_session("-Users-me-work-alpha", "bare.jsonl",
                           [user_line("check the webhook retry path", DAY)], mtime_date=DAY)
        data = self.ex.build(DAY)
        self.assertEqual(data["sessions_seen"], 2)
        self.assertEqual(data["sessions_untitled"], 1)

    def test_counters_are_ints_not_containers(self):
        """Regression: the counter was once named `sessions`, which a later
        `for pn, sessions in projects.items()` rebound to a list. It shipped into
        the JSON as one."""
        self.write_session("-Users-me-work-alpha", "s1.jsonl",
                           [title_line("t"), user_line("trace the failing import", DAY)], mtime_date=DAY)
        data = self.ex.build(DAY)
        for k in ("sessions_seen", "sessions_untitled", "transcripts_touched",
                  "session_count", "project_count"):
            self.assertIsInstance(data[k], int, "%s should be an int" % k)


class TestGrouping(TranscriptCase):
    def test_groups_sessions_by_project(self):
        self.write_session("-Users-me-work-alpha", "a.jsonl",
                           [title_line("A"), user_line("work on the alpha service", DAY)], mtime_date=DAY)
        self.write_session("-Users-me-work-beta", "b.jsonl",
                           [title_line("B"), user_line("work on the beta service", DAY)], mtime_date=DAY)
        names = {p["name"] for p in self.ex.build(DAY)["projects"]}
        self.assertEqual(len(names), 2)

    def test_busiest_project_sorts_first(self):
        self.write_session("-Users-me-work-quiet", "q.jsonl",
                           [title_line("Q"), user_line("one quick change here", DAY)], mtime_date=DAY)
        self.write_session("-Users-me-work-busy", "b.jsonl",
                           [title_line("B")] + [user_line("task number %d to do" % i, DAY) for i in range(5)],
                           mtime_date=DAY)
        projects = self.ex.build(DAY)["projects"]
        self.assertGreater(projects[0]["total"], projects[1]["total"])

    def test_dedups_near_identical_prompts(self):
        dupe = "run the same command again"
        self.write_session("-Users-me-work-alpha", "s.jsonl", [
            title_line("T"),
            user_line(dupe, DAY, "09:00"),
            user_line(dupe, DAY, "09:05"),
            user_line("something genuinely different", DAY, "09:10"),
        ], mtime_date=DAY)
        prompts = self.ex.build(DAY)["projects"][0]["sessions"][0]["prompts"]
        self.assertEqual(len(prompts), 2)


class TestDateFiltering(TranscriptCase):
    def test_rows_from_other_days_are_excluded(self):
        self.write_session("-Users-me-work-alpha", "s.jsonl", [
            title_line("T"),
            user_line("yesterday work", OTHER, "10:00"),
            user_line("today work", DAY, "10:00"),
        ], mtime_date=DAY)
        prompts = self.ex.build(DAY)["projects"][0]["sessions"][0]["prompts"]
        self.assertEqual([p["text"] for p in prompts], ["today work"])

    def test_a_day_with_no_rows_yields_no_projects(self):
        self.write_session("-Users-me-work-alpha", "s.jsonl",
                           [title_line("T"), user_line("old", OTHER)], mtime_date=OTHER)
        self.assertEqual(self.ex.build(DAY)["projects"], [])


class TestExclusion(TranscriptCase):
    def test_excluded_projects_never_appear(self):
        self.write_session("-Users-me-work-secret", "s.jsonl",
                           [title_line("Client work"), user_line("confidential client work", DAY)], mtime_date=DAY)
        self.write_session("-Users-me-work-alpha", "a.jsonl",
                           [title_line("Open work"), user_line("ordinary open source work", DAY)], mtime_date=DAY)
        secret_key = self.ex.proj_name(
            os.path.join(self.claude, "-Users-me-work-secret", "s.jsonl"))
        self.ex.EXCLUDE = {secret_key}
        names = [p["name"] for p in self.ex.build(DAY)["projects"]]
        self.assertEqual(len(names), 1)
        self.assertNotIn("secret", " ".join(names).lower())


class TestMalformedInput(TranscriptCase):
    def test_a_bad_line_does_not_lose_the_session(self):
        self.write_session("-Users-me-work-alpha", "s.jsonl", [
            title_line("T"),
            "{ this is not json",
            user_line("real prompt survives", DAY),
        ], mtime_date=DAY)
        prompts = self.ex.build(DAY)["projects"][0]["sessions"][0]["prompts"]
        self.assertEqual([p["text"] for p in prompts], ["real prompt survives"])

    def test_empty_file_is_skipped_quietly(self):
        self.write_session("-Users-me-work-alpha", "empty.jsonl", [""], mtime_date=DAY)
        self.assertEqual(self.ex.build(DAY)["projects"], [])


if __name__ == "__main__":
    unittest.main()
