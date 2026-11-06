"""Timesheet CSV export.

People paste this into billing, so the arithmetic has to be the rule the docs
state (last prompt minus first, per session) and nothing else, and an empty day
has to produce a valid file rather than no file.
"""

import csv
import io
import os
import subprocess
import sys
import tempfile
import shutil
import unittest

from harness import ROOT_DIR, TranscriptCase, user_line

MON, TUE, THU = "2026-08-03", "2026-08-04", "2026-08-06"
HEADER = ["date", "project", "source", "start", "end", "minutes", "sessions"]


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.reader(f))


class TestDay(TranscriptCase):
    def test_two_projects(self):
        # alpha: two sessions, 09:00-10:30 (90) and 14:00-14:15 (15).
        self.write_session("-Users-me-work-alpha", "a1.jsonl", [
            user_line("start the checkout refactor", THU, "09:00"),
            user_line("now split the rounding helper", THU, "10:30"),
        ], mtime_date=THU)
        self.write_session("-Users-me-work-alpha", "a2.jsonl", [
            user_line("review the refactor diff", THU, "14:00"),
            user_line("tidy the test names", THU, "14:15"),
        ], mtime_date=THU)
        # beta: one prompt only, so 0 minutes by the stated rule.
        self.write_session("-Users-me-work-beta", "b1.jsonl", [
            user_line("why does the webhook retry twice", THU, "11:00"),
        ], mtime_date=THU)

        path = self.ex.export_csv(THU)
        self.assertEqual(path, os.path.join(self.ex.CACHE, "timesheet-%s.csv" % THU))
        rows = read_csv(path)
        self.assertEqual(rows[0], HEADER)
        self.assertEqual(rows[1:], [
            [THU, "Users Me Work Alpha", "claude", "09:00", "14:15", "105", "2"],
            [THU, "Users Me Work Beta", "claude", "11:00", "11:00", "0", "1"],
        ])

    def test_empty_day_is_header_only(self):
        path = self.ex.export_csv(THU)
        self.assertEqual(read_csv(path), [HEADER])

    def test_out_overrides_the_path(self):
        out = os.path.join(self.tmp, "elsewhere", "ts.csv")
        self.assertEqual(self.ex.export_csv(THU, out=out), out)
        self.assertEqual(read_csv(out), [HEADER])

    def test_commas_and_quotes_in_names_survive(self):
        rows = self.ex.day_rows({"date": THU, "projects": [{
            "name": 'acme, "core"', "sessions": [
                {"start": "09:00", "end": "09:10", "source": "codex"}]}]})
        back = list(csv.reader(io.StringIO(self.ex.to_csv(rows))))
        self.assertEqual(back[1][1], 'acme, "core"')
        self.assertEqual(back[1][2], "codex")


class TestWeek(TranscriptCase):
    def test_week_has_a_row_per_project_per_day(self):
        self.write_session("-Users-me-work-alpha", "mon.jsonl", [
            user_line("plan the week", MON, "09:00"),
            user_line("write the ticket", MON, "09:45"),
        ], mtime_date=MON)
        self.write_session("-Users-me-work-alpha", "thu.jsonl", [
            user_line("ship the fix", THU, "16:00"),
            user_line("write the release note", THU, "16:20"),
        ], mtime_date=THU)
        self.write_session("-Users-me-work-beta", "tue.jsonl", [
            user_line("debug the importer", TUE, "10:00"),
            user_line("add a regression test", TUE, "11:00"),
        ], mtime_date=TUE)

        path = self.ex.export_csv(THU, week=True)
        self.assertEqual(os.path.basename(path), "timesheet-week-%s.csv" % MON)
        rows = read_csv(path)
        self.assertEqual(rows[0], HEADER)
        # In date order; Wednesday had nothing and contributes no row.
        self.assertEqual(rows[1:], [
            [MON, "Users Me Work Alpha", "claude", "09:00", "09:45", "45", "1"],
            [TUE, "Users Me Work Beta", "claude", "10:00", "11:00", "60", "1"],
            [THU, "Users Me Work Alpha", "claude", "16:00", "16:20", "20", "1"],
        ])


class TestCli(unittest.TestCase):
    def test_subcommand_prints_a_path_it_wrote(self):
        tmp = tempfile.mkdtemp(prefix="eod-ts-")
        try:
            out = os.path.join(tmp, "t.csv")
            r = subprocess.run([sys.executable, os.path.join(ROOT_DIR, "bin", "eod"),
                                "timesheet", "--date", THU, "--out", out],
                               cwd=tmp, capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertEqual(r.stdout.strip(), out)
            self.assertEqual(read_csv(out)[0], HEADER)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
