"""parse_warning(): the check that exists because a silent failure already cost four days.

Two shapes of fault, and one of them is the one that actually happened. Claude Code
renamed its title record and every session quietly fell back to its raw first prompt.
WORK stayed full, so a zero-work check would have said nothing at all.
"""

import unittest

from harness import TranscriptCase, load_extract, title_line, user_line

DAY = "2026-08-06"


def day(projects=0, touched=0, seen=0, untitled=0):
    return {
        "projects": [{"name": "p"}] * projects,
        "transcripts_touched": touched,
        "sessions_seen": seen,
        "sessions_untitled": untitled,
    }


class TestQuiet(unittest.TestCase):
    """Cases that must NOT warn. A canary that cries wolf gets ignored, which
    leaves you worse off than having none."""

    def setUp(self):
        self.ex = load_extract()

    def test_healthy_day(self):
        self.assertIsNone(self.ex.parse_warning(day(projects=3, touched=4, seen=4)))

    def test_genuinely_quiet_day(self):
        self.assertIsNone(self.ex.parse_warning(day()))

    def test_past_date_with_nothing_written_that_day(self):
        self.assertIsNone(self.ex.parse_warning(day(projects=2, touched=0, seen=2)))

    def test_a_couple_of_untitled_sessions_is_normal(self):
        """A session that has not earned a title yet is ordinary, not a fault."""
        self.assertIsNone(self.ex.parse_warning(day(projects=1, touched=2, seen=2, untitled=2)))

    def test_some_titles_missing_is_normal(self):
        self.assertIsNone(self.ex.parse_warning(day(projects=1, touched=5, seen=5, untitled=2)))

    def test_empty_dict_does_not_raise(self):
        self.assertIsNone(self.ex.parse_warning({}))


class TestWarns(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()

    def test_transcripts_written_but_nothing_parsed(self):
        w = self.ex.parse_warning(day(projects=0, touched=12, seen=0))
        self.assertIsNotNone(w)
        self.assertIn("12", w)
        self.assertIn("none parsed", w)

    def test_singular_reads_correctly(self):
        self.assertIn("1 session written", self.ex.parse_warning(day(touched=1)))

    def test_the_title_rename(self):
        """The real one. Sessions parse, WORK is populated, and not one line is a
        real title because the record moved."""
        w = self.ex.parse_warning(day(projects=2, touched=6, seen=6, untitled=6))
        self.assertEqual(w, "6 sessions, not one with a title")

    def test_threshold_is_three(self):
        self.assertIsNone(self.ex.parse_warning(day(projects=1, seen=2, untitled=2)))
        self.assertEqual(self.ex.parse_warning(day(projects=1, seen=3, untitled=3)),
                         "3 sessions, not one with a title")


class TestEndToEnd(TranscriptCase):
    def test_a_renamed_title_record_trips_the_canary(self):
        """Simulate the upstream schema change: the title record uses a key we do
        not read. Every session falls back, and the receipt should say so."""
        for i in range(4):
            self.write_session("-Users-me-work-alpha", "s%d.jsonl" % i, [
                '{"type": "brand-new-title-record", "someNewField": "A real title"}',
                user_line("do the work item number %d" % i, DAY),
            ], mtime_date=DAY)
        data = self.ex.build(DAY)
        self.assertTrue(data["projects"], "WORK should still be populated")
        self.assertEqual(data["sessions_seen"], 4)
        self.assertEqual(data["sessions_untitled"], 4)
        self.assertIsNotNone(self.ex.parse_warning(data))

    def test_healthy_build_stays_silent(self):
        for i in range(4):
            self.write_session("-Users-me-work-alpha", "s%d.jsonl" % i, [
                title_line("A genuine title %d" % i),
                user_line("do the work item number %d" % i, DAY),
            ], mtime_date=DAY)
        self.assertIsNone(self.ex.parse_warning(self.ex.build(DAY)))

    def test_warning_reaches_the_rendered_receipt(self):
        for i in range(4):
            self.write_session("-Users-me-work-alpha", "s%d.jsonl" % i, [
                user_line("do the work item number %d" % i, DAY),
            ], mtime_date=DAY)
        html = self.ex.to_html(self.ex.build(DAY))
        self.assertIn("class='warn'", html)
        self.assertEqual(html.count("class='warn'"), 1, "warning should appear once")


if __name__ == "__main__":
    unittest.main()
