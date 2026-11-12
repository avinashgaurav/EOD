"""The redesigned receipt (audit F28 to F42): hierarchy, icons, accessibility."""

import json, os, re, tempfile, unittest

from harness import load_extract

HERE = os.path.dirname(os.path.abspath(__file__))


def mod(ex, name):
    return next(m for m in ex._mods if m.__name__ == name)


class TestReceipt(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()
        self.h = mod(self.ex, "eod.render.html")
        self.cfg = mod(self.ex, "eod.config")
        self.tmp = tempfile.mkdtemp()
        self.cfg.APP_DIR = self.tmp
        with open(os.path.join(HERE, "snapshots", "day.json")) as fh:
            self.day = json.load(fh)
        self.day["highlights"] = ["Fixed the parser."]
        self.day["web"] = [{"host": "github.com", "count": 3, "titles": [], "start": "10:00", "end": "11:00"}]

    def page(self, **kw):
        return self.h.to_html(dict(self.day, **kw), send_to=["Slack"])

    def test_no_glyph_or_emoji_buttons(self):
        page = self.page()
        for g in ("⧉", "⎙", "⟳", "＋", "💾", "✎", "◀", "▶", "⇪", "↗", "↻"):
            self.assertNotIn(g, page, g)
        self.assertIn("class='ic'", page)

    def test_every_button_has_a_name(self):
        unnamed = []
        for attrs, inner in re.findall(r"<button([^>]*)>(.*?)</button>", self.page(), re.S):
            text = re.sub(r"<[^>]+>", "", inner).strip()
            if not text and "aria-label" not in attrs:
                unnamed.append(attrs)
        self.assertEqual(unnamed, [], "icon-only buttons need an aria-label")

    def test_one_primary_action_and_more_menu(self):
        page = self.page()
        self.assertEqual(len(re.findall(r"class='copyall primary' onclick=", page)), 1)
        for item in ("Full day", "Share as image", "Print receipt", "Copy update as", "Markdown", "Jira"):
            self.assertIn(item, page)
        self.assertNotIn("REF</span>", page.upper().replace("REFRESH", ""))

    def test_sites_only_on_brief_when_asked(self):
        shown = "<b>•</b>github.com"
        self.assertNotIn(shown, self.page())
        open(os.path.join(self.tmp, "brief-web.on"), "w").close()
        self.assertIn(shown, self.page())

    def test_source_chips(self):
        page = self.page(sources_status=[{"name": "git", "state": "ok"}, {"name": "meetings", "state": "failed"},
                                         {"name": "web", "state": "off"}, {"name": "github", "state": "missing"}])
        self.assertIn("Calendar: fix", page)
        self.assertIn("chip off", page)
        self.assertNotIn("GitHub", page)

    def test_toast_is_announced(self):
        self.assertIn("id='toast' role='status' aria-live='polite'", self.page())

    def test_contrast_tokens(self):
        css = self.h.CSS
        self.assertIn("--ink2:#5F5B54", css)
        self.assertIn("button:focus-visible", css)
        self.assertIn("min-width:24px;min-height:24px", css)


class TestSafety(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()
        self.h = mod(self.ex, "eod.render.html")
        with open(os.path.join(HERE, "snapshots", "day.json")) as fh:
            self.day = json.load(fh)

    def test_source_names_are_escaped(self):
        page = self.h.to_html(dict(self.day, sources_status=[{"name": "<img src=x onerror=alert(1)>'\"", "state": "failed"}]))
        self.assertNotIn("<img src=x", page)

    def test_app_only_controls_and_print_sheet(self):
        page = self.h.to_html(dict(self.day, highlights=["A."]))
        self.assertIn("class='app-only' onclick=\"closeMore(this);send({action:'print'})", page)
        self.assertIn("(window.EOD_APP?' app':'')", page)
        self.assertIn("@media print", page)

    def test_send_text_file_must_live_in_the_cache(self):
        import subprocess, sys
        root = os.path.dirname(HERE)
        r = subprocess.run([sys.executable, os.path.join(root, "extract.py"), "--send", "--text-file", "/etc/hosts"],
                           capture_output=True, text=True, env=dict(os.environ, EOD_SEND_TARGETS="slack https://example.invalid/x"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("must be a file EOD wrote", r.stderr)

    def test_bullets_are_rewritten_only_at_line_start(self):
        send = mod(self.ex, "eod.send")
        self.assertEqual(send._text({"_send_text": "H\n\u2022 a \u2022 b"}, bullet="- "), "H\n- a \u2022 b\n")


class TestWeeklyAndShare(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()
        self.h = mod(self.ex, "eod.render.html")
        self.cfg = mod(self.ex, "eod.config")
        self.tmp = tempfile.mkdtemp()
        self.cfg.APP_DIR = self.tmp

    def test_weekly_tldr_folds_and_sends(self):
        w = {"week_start": "2026-11-09", "week_end": "2026-11-13", "generated_at": "2026-11-13 18:05:00",
             "source_problems": [], "highlights": ["A."], "report": {"tldr": "Shipped A.", "blockers": [], "progress": ["P."]},
             "detailed": [], "time": {}, "tickets": {}}
        page = self.h.to_html_weekly(w, send_to=["Slack"])
        self.assertIn("<div class='tldr' role='note'>Shipped A.</div>", page)
        self.assertIn("<details class='dept wsec' data-title='Overall progress'>", page)
        self.assertIn("postWeekly(this)", page)
        self.assertIn("Export timesheet (CSV)", page)

    def test_share_lines_can_be_left_out(self):
        with open(os.path.join(HERE, "snapshots", "day.json")) as fh:
            d = json.load(fh)
        d["highlights"] = ["Secret project line."]
        self.assertIn("Secret project line.", self.h.to_html_share(d))
        open(os.path.join(self.tmp, "share-lines.off"), "w").close()
        self.assertNotIn("Secret project line.", self.h.to_html_share(d))


class TestExactTextSend(unittest.TestCase):
    def test_weekly_text_is_sent_as_previewed(self):
        send = mod(load_extract(), "eod.send")
        t = send._text({"_send_text": "Weekly update: x\n\n• A.\n"}, bullet="- ")
        self.assertEqual(t, "Weekly update: x\n\n- A.\n")
        self.assertIsNone(send._text({"_send_text": "  "}))


if __name__ == "__main__":
    unittest.main()
