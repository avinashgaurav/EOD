"""Reliability and honest status (audit F11 to F16)."""

import json, os, unittest

from harness import load_extract

HERE = os.path.dirname(os.path.abspath(__file__))


def mod(ex, name):
    return next(m for m in ex._mods if m.__name__ == name)


class TestFriendlyReasons(unittest.TestCase):
    def setUp(self):
        self.p = mod(load_extract(), "eod.polish")

    def test_each_cause_names_a_fix(self):
        f = self.p.friendly_reason
        self.assertIn("Install Claude Code", f("no claude CLI found"))
        self.assertIn("log in", f("claude exit 1: Please run /login"))
        self.assertIn("Ollama isn't running", f("URLError: Connection refused"))
        self.assertIn("took too long", f("TimeoutExpired: timed out"))
        self.assertIn("⟳", f("ValueError: something odd"))
        for msg in ("no claude cli", "login", "refused", "timeout", "weird"):
            self.assertNotIn("polish-error.log", f(msg))


class TestProvenance(unittest.TestCase):
    def setUp(self):
        ex = load_extract()
        self.h = mod(ex, "eod.render.html")
        with open(os.path.join(HERE, "snapshots", "day.json")) as fh:
            self.day = json.load(fh)

    def test_every_state_reads_plainly(self):
        pv = self.h.provenance
        self.assertEqual(pv({"summary": {"by": "claude", "at": "17:02"}}), "Summarized by Claude at 17:02")
        self.assertEqual(pv({"summary": {"by": "ollama", "at": "09:00"}}), "Summarized on this Mac by Ollama at 09:00")
        self.assertEqual(pv({"summary": {"by": "edited"}}), "Edited by you")
        self.assertTrue(pv({"summary": {"by": "stale", "at": "15:10", "note": "Press ⟳."}}).startswith("Last summary 15:10."))
        self.assertTrue(pv({"summary": {"by": "off"}}).startswith("Offline summary"))
        self.assertEqual(pv({}), "")

    def test_it_shows_under_work(self):
        d = dict(self.day, highlights=["Fixed it."], summary={"by": "claude", "at": "17:02"})
        page = self.h.to_html(d)
        self.assertIn("<div class='prov' role='note'>Summarized by Claude at 17:02</div>", page)

    def test_edit_keys_and_undo_are_on_the_page(self):
        page = self.h.to_html(dict(self.day, highlights=["Fixed it."]))
        for needle in ("_editKeys", "e.key==='Escape'", "_removeWithUndo", "_undoOne", "isComposing", "window.setStatus", "window.isEditing"):
            self.assertIn(needle, page)
        self.assertNotIn("💾", page)


if __name__ == "__main__":
    unittest.main()
