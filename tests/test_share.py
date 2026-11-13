"""The share image: the card it is drawn from, the PNG, and extract.py --share.

The card is the one EOD surface meant to leave the Mac, posted in public. So the
tests that matter most here are about what it leaves out: no prompts, no buttons,
no script, and nothing that changes between two renders of the same day.
"""

import contextlib
import io
import json
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

    def test_without_highlights_it_shows_totals_and_no_names(self):
        """The brief receipt's fallback prints session titles, and an untitled
        session is titled by its first prompt. Project names are no better:
        they come from the folder path, which can carry the macOS username.
        So without highlights the card shows the totals and nothing named."""
        card = self.ex.to_html_share(self._day())
        self.assertIn("Projects</span><span class='dots'></span><span class='v'>2<", card)
        low = card.lower()
        for private in ("private roadmap", "coupon rounding", "hunter2",
                        "users", "me work", "checkout", "search"):
            self.assertNotIn(private, low)

    def test_no_script_can_run_on_it(self):
        card = self.ex.to_html_share(self._day(["Shipped the coupon fix"]))
        self.assertIn("Content-Security-Policy", card)
        self.assertIn("default-src 'none'; style-src 'unsafe-inline'", card)

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

    def _run(self, png_result, date=DAY):
        calls = []

        def fake(html_path, png_path, w, h, **_):
            calls.append((html_path, png_path, w, h))
            if png_result is None:
                open(png_path, "wb").close()
            return png_result

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys.modules["eod.cli"], "html_to_png", fake), \
                mock.patch.object(sys, "argv", ["extract.py", "--date", date, "--share"]), \
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

    def test_never_calls_claude_or_rewrites_history(self):
        """A press of the share button must not send anything anywhere. Even
        with a claude CLI available and a day that has never been polished."""
        self.write_session("-Users-me-work-checkout", "a.jsonl", [
            title_line("Fix the coupon rounding edge case"),
            user_line(SECRET, DAY, "09:12"),
        ], mtime_date=DAY)
        claude, history = [], []
        self.ex._claude_bin = lambda: "/usr/local/bin/claude"
        self.ex._run_claude = lambda *a, **k: claude.append(a)
        self.ex.write_history = lambda: history.append(1)
        code, _, _, _ = self._run(None)
        self.assertEqual(code, 0)
        self.assertEqual(claude, [], "--share reached the claude CLI")
        self.assertEqual(history, [], "--share rewrote worklog-history.md")

    def test_uses_the_summary_already_on_disk(self):
        """Cached or hand-edited highlights are what the panel shows; the card matches."""
        with open(os.path.join(self.ex.CACHE, "polish-%s.json" % DAY), "w") as f:
            json.dump({"key": "edited", "highlights": ["Hand-edited line"], "edited": True}, f)
        self.write_session("-Users-me-work-checkout", "a.jsonl", [
            user_line("anything", DAY, "09:12")], mtime_date=DAY)
        _, _, _, calls = self._run(None)
        with open(calls[0][0]) as f:
            self.assertIn("Hand-edited line", f.read())

    def test_rejects_a_date_that_is_not_one(self):
        for bad in ("2026-13-40", "../../etc", "2026-8-6", "today"):
            code, out, err, calls = self._run(None, date=bad)
            self.assertEqual(code, 2, bad)
            self.assertEqual(calls, [], bad)
            self.assertIn("YYYY-MM-DD", err)


class TestPng(TranscriptCase):

    def test_off_macos_it_reports_instead_of_pretending(self):
        image = sys.modules["eod.render.image"]
        with mock.patch.object(image.sys, "platform", "linux"):
            why = image.html_to_png("x.html", os.path.join(self.tmp, "x.png"), 1200, 675)
        self.assertIn("macOS", why)

    def test_a_hung_drawing_says_timed_out(self):
        image = sys.modules["eod.render.image"]
        boom = mock.Mock(side_effect=image.subprocess.TimeoutExpired("osascript", 30))
        with mock.patch.object(image.sys, "platform", "darwin"), \
                mock.patch.object(image.os.path, "exists", lambda p: True), \
                mock.patch.object(image.subprocess, "run", boom):
            why = image.html_to_png("x.html", "x.png", 1200, 675)
        self.assertIn("timed out", why)

    # Needs a logged-in Mac with a window server: CI machines have none, and the
    # release build must not hang on it (it runs the suite on macOS).
    @unittest.skipUnless(sys.platform == "darwin" and os.path.exists("/usr/bin/osascript")
                         and not os.environ.get("CI"), "drawing needs macOS WebKit on a desktop session")
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
