"""Settings the Mac app writes for the engine (audit F22, F26, #37)."""

import json, os, tempfile, unittest

from harness import load_extract


def mod(ex, name):
    return next(m for m in ex._mods if m.__name__ == name)


class TestSourcesOff(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()
        self.cfg = mod(self.ex, "eod.config")
        self.tmp = tempfile.mkdtemp()
        self.cfg.APP_DIR = self.tmp

    def test_file_lists_switched_off_sources(self):
        with open(os.path.join(self.tmp, "sources.off"), "w") as fh:
            fh.write("Web\n# note\napps\n\n")
        self.assertEqual(self.cfg.load_sources_off(), {"web", "apps"})

    def test_no_file_means_everything_on(self):
        self.assertEqual(self.cfg.load_sources_off(), set())

    def test_switched_off_sources_are_never_read(self):
        with open(os.path.join(self.tmp, "sources.off"), "w") as fh:
            fh.write("web\napps\ngit\ngithub\ndocs\nmeetings\n")
        pipe = mod(self.ex, "eod.pipeline")
        reg = mod(self.ex, "eod.sources.base")
        called = []
        for src in reg.registry():
            orig = src.collect
            src.collect = (lambda o, n: (lambda d: (called.append(n), o(d))[1]))(orig, src.name)
        pipe.collect_sources("2026-11-10")
        for n in ("web", "apps", "git", "github", "docs", "meetings"):
            self.assertNotIn(n, called)


class TestAppCalendar(unittest.TestCase):
    def test_app_calendar_wins_and_drops_attendees(self):
        ex = load_extract()
        cfg = mod(ex, "eod.config")
        meet = mod(ex, "eod.sources.meetings")
        tmp = tempfile.mkdtemp()
        meet.CACHE = tmp
        open(os.path.join(tmp, "calendar-enabled"), "w").close()
        with open(os.path.join(tmp, "calendar-2026-11-10.json"), "w") as fh:
            json.dump([{"title": "Design review", "time": "10:00", "attendees": "Sam"}, {"title": "All day", "time": ""}], fh)
        # read_meetings itself is stubbed by the harness; test the app-calendar path it prefers.
        self.assertTrue(meet.app_calendar_on())
        self.assertEqual(meet._app_calendar("2026-11-10"), [{"title": "Design review", "time": "10:00", "attendees": ""}])
        self.assertIsNone(meet._app_calendar("2026-11-11"))


if __name__ == "__main__":
    unittest.main()
