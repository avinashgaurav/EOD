"""Date handling and the mtime scan window.

The scan filter is an optimisation that silently drops files. If its bounds are
wrong the receipt simply loses work, with nothing to indicate it, so the edges
matter more here than almost anywhere else in the codebase.
"""

import os
import tempfile
import time
import unittest

from harness import day_epoch, load_extract

DAY = "2026-08-06"


class TestLocalDate(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()

    def test_parses_utc_into_local_date_and_time(self):
        d, hm = self.ex.local_date_of("2026-08-06T12:00:00Z")
        self.assertRegex(d, r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(hm, r"^\d{2}:\d{2}$")

    def test_round_trips_a_known_local_instant(self):
        """Whatever the runner's timezone, 09:30 local must come back as 09:30 local."""
        local = day_epoch(DAY, 0) + 9 * 3600 + 30 * 60
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(local))
        self.assertEqual(self.ex.local_date_of(ts), (DAY, "09:30"))

    def test_day_boundaries_land_on_the_right_day(self):
        for hh, mm in ((0, 0), (23, 59)):
            local = day_epoch(DAY, 0) + hh * 3600 + mm * 60
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(local))
            self.assertEqual(self.ex.local_date_of(ts)[0], DAY,
                             "%02d:%02d local fell outside %s" % (hh, mm, DAY))

    def test_garbage_timestamp_returns_none_rather_than_raising(self):
        self.assertEqual(self.ex.local_date_of("not a timestamp"), (None, None))
        self.assertEqual(self.ex.local_date_of(""), (None, None))


class TestScanWindow(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()
        self.tmp = tempfile.mkdtemp(prefix="eod-scan-")

    def _file(self, name, epoch):
        p = os.path.join(self.tmp, name)
        open(p, "w").close()
        os.utime(p, (epoch, epoch))
        return p

    def test_floor_sits_below_local_midnight(self):
        floor = self.ex._scan_floor(DAY)
        self.assertLessEqual(floor, day_epoch(DAY, 0))
        self.assertGreater(floor, day_epoch(DAY, 0) - 2 * self.ex.SCAN_MARGIN)

    def test_unparseable_date_disables_the_skip(self):
        """Falling back to scanning everything is correct; returning nothing is not."""
        self.assertEqual(self.ex._scan_floor("not-a-date"), 0.0)
        self.assertFalse(self.ex._predates(self._file("x.jsonl", 0), 0.0))

    def test_predates_only_skips_files_older_than_the_floor(self):
        floor = self.ex._scan_floor(DAY)
        self.assertTrue(self.ex._predates(self._file("old.jsonl", day_epoch("2026-07-01", 12)), floor))
        self.assertFalse(self.ex._predates(self._file("today.jsonl", day_epoch(DAY, 12)), floor))
        self.assertFalse(self.ex._predates(self._file("later.jsonl", day_epoch("2026-09-01", 12)), floor))

    def test_missing_file_is_not_skipped(self):
        """Cannot stat means unknown, and unknown must not silently drop work."""
        self.assertFalse(self.ex._predates(os.path.join(self.tmp, "nope.jsonl"),
                                           self.ex._scan_floor(DAY)))

    def test_written_during_is_narrower_than_predates(self):
        """This is the distinction the canary depends on. _predates keeps anything
        touched since the day; _written_during keeps only that day. Without it,
        every past date you page back to would raise a false alarm."""
        start, end = self.ex._day_window(DAY)
        later = self._file("later.jsonl", day_epoch("2026-09-01", 12))
        today = self._file("today.jsonl", day_epoch(DAY, 12))
        self.assertFalse(self.ex._predates(later, self.ex._scan_floor(DAY)))
        self.assertFalse(self.ex._written_during(later, start, end))
        self.assertTrue(self.ex._written_during(today, start, end))

    def test_window_edges_are_half_open(self):
        start, end = self.ex._day_window(DAY)
        self.assertTrue(self.ex._written_during(self._file("a", start), start, end))
        self.assertTrue(self.ex._written_during(self._file("b", end - 1), start, end))
        self.assertFalse(self.ex._written_during(self._file("c", end), start, end))
        self.assertFalse(self.ex._written_during(self._file("d", start - 1), start, end))

    def test_bad_date_yields_no_window(self):
        self.assertEqual(self.ex._day_window("nonsense"), (None, None))
        self.assertFalse(self.ex._written_during(self._file("e", 0), None, None))


if __name__ == "__main__":
    unittest.main()
