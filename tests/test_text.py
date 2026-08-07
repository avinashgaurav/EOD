"""Text helpers and whole-receipt rendering.

The noise filter decides what counts as work at all, so a change here silently
changes every receipt. The render tests are deliberately about invariants (the
day's work appears, the copy block matches) rather than exact markup, so ordinary
design edits do not break the suite.
"""

import unittest

from harness import EXTRACT, TranscriptCase, load_extract, title_line, user_line

DAY = "2026-08-06"


class TestNoiseFilter(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()

    def test_drops_bare_acknowledgements(self):
        for t in ("ok", "yes", "go", "..."):
            self.assertTrue(self.ex.is_noise(t), "%r should be noise" % t)

    def test_drops_empty_and_whitespace(self):
        for t in ("", "   ", "\n"):
            self.assertTrue(self.ex.is_noise(t))

    def test_drops_very_short_fragments(self):
        self.assertTrue(self.ex.is_noise("abc"))

    def test_keeps_real_instructions(self):
        for t in ("fix the flaky webhook test",
                  "why does the budget endpoint return zero for one tenant"):
            self.assertFalse(self.ex.is_noise(t), "%r should be kept" % t)

    def test_drops_harness_chatter(self):
        self.assertTrue(self.ex.is_noise("<task-id>abc</task-id>"))


class TestOneline(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()

    def test_collapses_newlines(self):
        self.assertNotIn("\n", self.ex.oneline("a line\nand another", 100))

    def test_respects_the_limit(self):
        self.assertLessEqual(len(self.ex.oneline("x" * 500, 40)), 40)

    def test_short_text_is_untouched(self):
        self.assertEqual(self.ex.oneline("already short", 100), "already short")


class TestSignature(unittest.TestCase):
    """The mark on the receipt must be the user's own, and must vanish cleanly."""

    def setUp(self):
        self.ex = load_extract()

    def test_no_signature_renders_no_separator(self):
        self.ex.SIG = ""
        self.assertEqual(self.ex._sig_html(), "")

    def test_signature_is_escaped(self):
        self.ex.SIG = "<script>"
        out = self.ex._sig_html()
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_no_hardcoded_initials_remain(self):
        """Regression: the author's initials were hardcoded via chr() codes and
        re-inserted by a guard if removed."""
        with open(EXTRACT) as fh:
            src = fh.read()
        self.assertNotIn("tamper-guard", src)
        self.assertNotIn("map(chr, (65, 71))", src)


class TestRender(TranscriptCase):
    def _build_a_day(self):
        self.write_session("-Users-me-work-alpha", "s.jsonl", [
            title_line("Fix the checkout rounding bug"),
            user_line("look at the coupon rounding edge case", DAY),
        ], mtime_date=DAY)
        return self.ex.build(DAY)

    def test_html_contains_the_work(self):
        html = self.ex.to_html(self._build_a_day())
        self.assertIn("checkout rounding bug", html)
        self.assertIn("</html>", html)

    def test_html_is_self_contained(self):
        """The receipt is loaded from file:// inside a webview with no network."""
        html = self.ex.to_html(self._build_a_day())
        for remote in ("http://", "https://", "//cdn", "src=\"//"):
            self.assertNotIn(remote, html, "receipt should not reference %s" % remote)

    def test_text_contains_the_work(self):
        self.assertIn("checkout rounding bug", self.ex.to_text(self._build_a_day()))

    def test_quiet_day_says_so(self):
        data = self.ex.build(DAY)
        self.assertIn("No activity recorded", self.ex.to_text(data))

    def test_all_three_renderers_survive_an_empty_day(self):
        """Empty input is the case most likely to raise, and the one a user hits
        first thing in the morning."""
        data = self.ex.build(DAY)
        for fn in (self.ex.to_html, self.ex.to_html_full, self.ex.to_text, self.ex.to_text_full):
            self.assertTrue(fn(data), "%s returned nothing" % fn.__name__)

    def test_html_escapes_hostile_titles(self):
        self.write_session("-Users-me-work-alpha", "x.jsonl", [
            title_line("<img src=x onerror=alert(1)>"),
            user_line("do something ordinary here", DAY),
        ], mtime_date=DAY)
        html = self.ex.to_html(self.ex.build(DAY))
        self.assertNotIn("<img src=x onerror", html)
        self.assertIn("&lt;img", html)




class TestCleanTitle(unittest.TestCase):
    """Session titles are rewritten before they hit the receipt. That surprised the
    render tests once, so the behaviour is pinned here rather than left implicit."""

    def setUp(self):
        self.ex = load_extract()

    def test_normalises_imperative_to_past_tense(self):
        self.assertEqual(self.ex.clean_title("Fix the checkout rounding bug"),
                         "Fixed the checkout rounding bug")

    def test_leaves_already_past_tense_alone(self):
        self.assertEqual(self.ex.clean_title("Shipped the redesign"), "Shipped the redesign")

    def test_empty_input_does_not_raise(self):
        self.assertIsNotNone(self.ex.clean_title(""))

if __name__ == "__main__":
    unittest.main()
