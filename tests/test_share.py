"""The share image: the card it is drawn from, the PNG, and extract.py --share.

The card is the one EOD surface meant to leave the Mac, posted in public. So the
tests that matter most here are about what it leaves out: no prompts, no buttons,
no script, and nothing that changes between two renders of the same day.
"""

import contextlib
import io
import os
import struct
import sys
import unittest
from unittest import mock

from harness import TranscriptCase, title_line, user_line

DAY = "2026-08-06"
SECRET = "paste the staging password hunter2 into the config"


class TestShareCard(TranscriptCase):

    def _day(self, highlights=None):
        self.write_session("-Users-me-work-checkout", "a.jsonl", [
            title_line("Fix the coupon rounding edge case"),
            user_line(SECRET, DAY, "09:12"),
        ], mtime_date=DAY)
        # untitled: its title falls back to the first prompt, which is the leak
        self.write_session("-Users-me-work-search", "b.jsonl", [
            user_line("an untitled session about the private roadmap", DAY, "11:55"),
        ], mtime_date=DAY)
        data = self.ex.build(DAY)
        if highlights is not None:
            data["highlights"] = highlights
        return data

    def test_has_the_footer_and_no_controls(self):
        card = self.ex.to_html_share(self._day(["Shipped the coupon fix"]))
        self.assertIn("made with <b>EOD</b>", card)
        for control in ("<button", "<script", "onclick", "<input", "contenteditable"):
            self.assertNotIn(control, card)

    def test_carries_highlights_and_never_a_prompt(self):
        data = self._day(["Shipped the coupon fix"])
        card = self.ex.to_html_share(data)
        self.assertIn("Shipped the coupon fix", card)
        self.assertNotIn("hunter2", card)
        self.assertIn("hunter2", self.ex.to_html_full(data), "the fixture must contain the prompt")

    def test_without_highlights_it_shows_projects_not_titles(self):
        """The brief receipt's fallback prints session titles, and an untitled
        session is titled by its first prompt. The card stops at project names."""
        card = self.ex.to_html_share(self._day())
        self.assertIn("Work Search", card)
        self.assertNotIn("private roadmap", card)
        self.assertNotIn("coupon rounding", card)

    def test_long_days_are_capped(self):
        n = self.ex.SHARE_MAX_LINES
        card = self.ex.to_html_share(self._day(["line %d" % i for i in range(n + 3)]))
        self.assertIn("line %d" % (n - 1), card)
        self.assertNotIn("line %d<" % n, card)
        self.assertIn("+ 3 more", card)

    def test_same_day_same_card(self):
        """Deterministic: the refresh timestamp is not on the card."""
        data = self._day(["Shipped the coupon fix"])
        a = self.ex.to_html_share(data)
        data["generated_at"] = "2099-01-01 23:59:59"
        self.assertEqual(a, self.ex.to_html_share(data))

    def test_self_contained_and_survives_an_empty_day(self):
        card = self.ex.to_html_share(self.ex.build(DAY))
        self.assertIn("NO ACTIVITY LOGGED", card)
        for remote in ("http://", "https://", "//cdn"):
            self.assertNotIn(remote, card)


class TestShareCommand(TranscriptCase):
    """extract.py --share, with the drawing step stubbed: what eod.lua relies on."""

    def _run(self, png_result):
        calls = []

        def fake(html_path, png_path, w, h, **_):
            calls.append((html_path, png_path, w, h))
            if png_result is None:
                open(png_path, "wb").close()
            return png_result

        self.ex.html_to_png = fake
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["extract.py", "--date", DAY, "--share"]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                self.ex.main()
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue(), calls

    def test_prints_the_png_path(self):
        code, out, _, calls = self._run(None)
        png = os.path.join(self.ex.CACHE, DAY + "-share.png")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "SHARE " + png)
        self.assertEqual(calls[0][2:], (1200, 675))
        with open(calls[0][0]) as f:
            self.assertIn("made with", f.read())

    def test_a_failed_drawing_exits_nonzero_and_says_why(self):
        code, out, err, _ = self._run("the share image needs macOS")
        self.assertEqual(code, 1)
        self.assertNotIn("SHARE", out)
        self.assertIn("needs macOS", err)


class TestPng(TranscriptCase):

    def test_off_macos_it_reports_instead_of_pretending(self):
        image = sys.modules["eod.render.image"]
        with mock.patch.object(image.sys, "platform", "linux"):
            why = image.html_to_png("x.html", os.path.join(self.tmp, "x.png"), 1200, 675)
        self.assertIn("macOS", why)

    @unittest.skipUnless(sys.platform == "darwin" and os.path.exists("/usr/bin/osascript"),
                         "drawing needs macOS WebKit")
    def test_draws_a_2x_png_at_the_social_size(self):
        html_path = os.path.join(self.tmp, "card.html")
        png_path = os.path.join(self.tmp, "card.png")
        with open(html_path, "w") as f:
            f.write(self.ex.to_html_share(self.ex.build(DAY)))
        why = self.ex.html_to_png(html_path, png_path, self.ex.SHARE_W, self.ex.SHARE_H)
        self.assertIsNone(why)
        with open(png_path, "rb") as f:
            head = f.read(24)
        self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", head[16:24]), (2400, 1350))


if __name__ == "__main__":
    unittest.main()
