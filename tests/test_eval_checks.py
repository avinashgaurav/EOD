"""The automatic overstatement check used by the polish test (evals/harness/claims_check.py).

It replaced a hand read, so it has to agree with that read. On the saved
2026-10-15 outputs it must flag the same five days the author found before the
prompt fix, and nothing after it. It must also keep flagging plain claims the
new cases were built to catch, while letting "to be published" through.
No model is called here.
"""

import json
import os
import sys
import unittest

from harness import ROOT_DIR, load_extract

sys.path.insert(0, os.path.join(ROOT_DIR, "evals", "harness"))
import claims_check as C  # noqa: E402


def _load(*parts):
    with open(os.path.join(ROOT_DIR, *parts)) as fh:
        return json.load(fh)


class TestClaimsCheck(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()

    def _flags(self, case, lines):
        payload = self.ex._polish_input(case["data"])
        return C.check(lines, payload, case, bool(case["data"].get("meetings")))

    def _flagged_days(self, results_file):
        cases = {d["id"]: d for d in _load("evals", "datasets", "days.json")["days"]}
        res = _load("evals", "results", results_file)["results"]
        return sorted(r["id"] for r in res if self._flags(cases[r["id"]], C.lines_of(r["output"])))

    def test_agrees_with_the_hand_read_before_the_fix(self):
        # Hand read: overstated on day02 and day10, small additions on day01, day03, day07.
        self.assertEqual(self._flagged_days("2026-10-15-claude-cli.json"),
                         ["day01", "day02", "day03", "day07", "day10"])

    def test_agrees_with_the_hand_read_after_the_fix(self):
        self.assertEqual(self._flagged_days("2026-10-15-claude-cli-after-fix.json"), [])

    def test_new_cases_catch_plain_claims(self):
        days = {d["id"]: d for d in _load("evals", "datasets", "days-new.json")["days"]}
        caught = {
            "new01": "Refund fix deployed to production",
            "new02": "Sent the October newsletter to Marisol's list",
            "new03": "Worked with Anjali on the CSV export",
            "new04": "Set up the nightly revenue cube refresh",
            "new05": "Merged offline drafts (#742) and shipped in 2.8",
            "new06": "Pricing proposal v2 approved by Noor",
            "new08": "Published the Halvorsen case study",
            "new10": "Shared the migration note with Support",
        }
        for day, line in caught.items():
            self.assertTrue(self._flags(days[day], [line]), "%s: %r should be flagged" % (day, line))

    def test_pending_steps_and_supported_outcomes_pass(self):
        days = {d["id"]: d for d in _load("evals", "datasets", "days-new.json")["days"]}
        fine = {
            "new01": "Fixed JPY refund rounding (#1184) and deployed it to staging",
            "new03": "Built CSV export (#1302), merged in PR #1311",
            "new08": "Drafted the case study, to be published by Mateo after sign-off",
            "new09": "Weekly broken link check on the docs build",
            "new02": "Applied Henrik's edits to the deck shared with him this morning",
        }
        # A pending step the input never plans is still an invented outcome.
        self.assertTrue(self._flags(days["new07"], ["Query fix to be shipped tomorrow"]))
        for day, line in fine.items():
            self.assertEqual(self._flags(days[day], [line]), [], "%s: %r should pass" % (day, line))


if __name__ == "__main__":
    unittest.main()
