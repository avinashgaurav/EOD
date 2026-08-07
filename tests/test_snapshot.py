"""Whole-pipeline snapshot: a fixed synthetic day, rendered every way, byte-compared.

The unit tests check pieces. This checks that the pieces still add up to the same
receipt, which is what actually protects a refactor. It caught nothing when the
package split landed, and that was the point: it proved the split changed nothing.

Regenerate deliberately, never casually:

    EOD_UPDATE_SNAPSHOTS=1 ./run_tests.sh test_snapshot

and read the resulting diff before committing it.
"""

import os
import unittest

from harness import TranscriptCase, title_line, user_line

DAY = "2026-08-06"
SNAP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")


class TestSnapshot(TranscriptCase):
    def _fixed_day(self):
        """A deterministic day: three projects, mixed titles, a duplicate prompt,
        one untitled session, and a row from the day before that must not appear."""
        self.write_session("-Users-me-work-checkout", "a.jsonl", [
            title_line("Fix the coupon rounding edge case"),
            user_line("look at the coupon rounding edge case", DAY, "09:12"),
            user_line("look at the coupon rounding edge case", DAY, "09:14"),  # dupe
            user_line("add a regression test for that path", DAY, "09:40"),
        ], mtime_date=DAY)
        self.write_session("-Users-me-work-search", "b.jsonl", [
            title_line("Review the indexing pull request"),
            user_line("review PR 501 for the search service", DAY, "11:55"),
            user_line("yesterday leftover that must not appear", "2026-08-05", "23:00"),
        ], mtime_date=DAY)
        self.write_session("-Users-me-work-platform", "c.jsonl", [
            user_line("trace why the webhook retries twice", DAY, "15:30"),
        ], mtime_date=DAY)
        data = self.ex.build(DAY)
        data["generated_at"] = "2026-08-06 17:00:00"   # the only wall-clock field
        return data

    def _check(self, name, actual):
        os.makedirs(SNAP_DIR, exist_ok=True)
        path = os.path.join(SNAP_DIR, name)
        if os.environ.get("EOD_UPDATE_SNAPSHOTS"):
            with open(path, "w") as f:
                f.write(actual)
            self.skipTest("snapshot %s rewritten" % name)
        if not os.path.exists(path):
            self.fail("no snapshot %s; run EOD_UPDATE_SNAPSHOTS=1 ./run_tests.sh test_snapshot"
                      % name)
        with open(path) as f:
            expected = f.read()
        if expected != actual:
            self.fail("%s changed. If that was intended, regenerate with "
                      "EOD_UPDATE_SNAPSHOTS=1 and read the diff before committing." % name)

    def test_text_receipt(self):
        self._check("day.txt", self.ex.to_text(self._fixed_day()))

    def test_full_text_receipt(self):
        self._check("day-full.txt", self.ex.to_text_full(self._fixed_day()))

    def test_html_receipt(self):
        self._check("day.html", self.ex.to_html(self._fixed_day()))

    def test_full_html_receipt(self):
        self._check("day-full.html", self.ex.to_html_full(self._fixed_day()))

    def test_the_day_itself(self):
        """The parsed shape, before any rendering."""
        import json
        self._check("day.json", json.dumps(self._fixed_day(), sort_keys=True,
                                           indent=1, default=str))


if __name__ == "__main__":
    unittest.main()
