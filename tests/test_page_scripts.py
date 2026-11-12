"""Every script on every page EOD draws must parse. The receipt's JS lives in
Python strings, where one wrong escape turns a '\\n' into a real newline inside
a JS string literal and silently kills every button on the card."""

import json, os, re, shutil, subprocess, unittest

from harness import load_extract

HERE = os.path.dirname(os.path.abspath(__file__))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestPageScripts(unittest.TestCase):
    def pages(self):
        ex = load_extract()
        with open(os.path.join(HERE, "snapshots", "day.json")) as fh:
            day = json.load(fh)
        polished = dict(day, highlights=['Fixed the "quoted" bug.', "Line with </script> in it."])
        week = {"week_start": "2026-11-09", "week_end": "2026-11-13", "generated_at": "2026-11-13 18:05:00",
                "source_problems": [], "highlights": ["A."], "report": {"blockers": []},
                "detailed": [], "time": {}, "tickets": {}}
        return [ex.to_html(day), ex.to_html(polished, send_to=["Slack"]), ex.to_html_full(day),
                ex.to_html_weekly(week)]

    def test_every_script_parses(self):
        for page in self.pages():
            for js in re.findall(r"<script>(.*?)</script>", page, re.S):
                r = subprocess.run(["node", "--check", "-"], input=js, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr[:500])


if __name__ == "__main__":
    unittest.main()
