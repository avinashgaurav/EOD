"""The source contract, the registry, and third-party plugins.

The point of the contract is that "not set up" and "broken" stop looking the same
from the outside. Most of these tests are about that distinction, because getting
it wrong is what produced a convincing empty section for four days.
"""

import os
import shutil
import tempfile
import unittest

from harness import TranscriptCase, load_extract, title_line, user_line

DAY = "2026-08-06"

PLUGIN = '''
from eod.sources.base import Source, register


class LinearSource(Source):
    name = "linear"
    section = "SHIPPED"
    key = "linear_issues"
    summary = "Issues you moved today"

    def available(self):
        return True

    def read(self, date):
        return [{"id": "ENG-1", "title": "closed the flaky test"}]


register(LinearSource())
'''

BROKEN_PLUGIN = "import a_module_that_does_not_exist\n"

FAILING_SOURCE = '''
from eod.sources.base import Source, register


class ExplodingSource(Source):
    name = "exploding"
    section = "WEB"
    key = "web"
    summary = "always blows up"

    def available(self):
        return True

    def read(self, date):
        raise RuntimeError("the credential expired")


register(ExplodingSource())
'''

UNAVAILABLE_SOURCE = '''
from eod.sources.base import Source, register


class NotSetUpSource(Source):
    name = "notsetup"
    section = "WEB"
    key = "web"
    requires = "a thing you have not installed"

    def available(self):
        return False

    def read(self, date):
        raise AssertionError("read() must not be called when unavailable")


register(NotSetUpSource())
'''


class TestContract(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()
        self.base = self.ex.__getattr__("Source"), None

    def _src(self, **kw):
        base = load_extract()
        Source = base.Source

        class S(Source):
            name = kw.get("name", "test")
            section = "WEB"
            key = "web"
        for k, v in kw.items():
            setattr(S, k, v)
        return S()

    def test_unavailable_source_is_silent(self):
        s = self._src(available=lambda self=None: False,
                      read=lambda self, d: 1 / 0)
        self.assertEqual(s.collect(DAY), ([], None))

    def test_failing_source_is_reported_not_raised(self):
        def boom(self, d):
            raise RuntimeError("the credential expired")
        s = self._src(available=lambda self=None: True, read=boom)
        items, err = s.collect(DAY)
        self.assertEqual(items, [])
        self.assertIn("credential expired", err)
        self.assertIn("RuntimeError", err)

    def test_available_that_raises_counts_as_unavailable(self):
        """A source too broken to answer 'are you set up' is not set up."""
        def boom(self=None):
            raise OSError("no such directory")
        s = self._src(available=boom, read=lambda self, d: ["x"])
        self.assertFalse(s.safe_available())
        self.assertEqual(s.collect(DAY), ([], None))

    def test_read_returning_none_is_treated_as_empty(self):
        s = self._src(available=lambda self=None: True, read=lambda self, d: None)
        self.assertEqual(s.collect(DAY), ([], None))


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.ex = load_extract()

    def test_builtins_are_registered(self):
        names = {s.name for s in self.ex.registry()}
        for expected in ("git", "github", "web", "apps", "docs", "meetings"):
            self.assertIn(expected, names)

    def test_order_is_stable(self):
        a = [s.name for s in self.ex.registry()]
        b = [s.name for s in self.ex.registry()]
        self.assertEqual(a, b)
        self.assertEqual(a, sorted(a), "unstable order would shuffle the receipt")

    def test_every_builtin_declares_its_contract(self):
        for s in self.ex.registry():
            self.assertTrue(s.name, "%r has no name" % s)
            self.assertTrue(s.section, "%s has no section" % s.name)

    def test_no_two_sources_share_a_key(self):
        """git and github both live in SHIPPED. Sharing a key merged PRs into the
        commit list, which the golden comparison caught."""
        keys = [s.key for s in self.ex.registry() if s.key]
        self.assertEqual(len(keys), len(set(keys)), "duplicate key: %s" % keys)


class PluginCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="eod-plugins-")
        os.environ["EOD_SOURCE_DIR"] = self.dir

    def tearDown(self):
        os.environ.pop("EOD_SOURCE_DIR", None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, name, body):
        with open(os.path.join(self.dir, name), "w") as f:
            f.write(body)


class TestPlugins(PluginCase):
    def test_a_plugin_registers_without_touching_the_repo(self):
        self._write("linear.py", PLUGIN)
        ex = load_extract()
        self.assertIn("linear", {s.name for s in ex.registry()})

    def test_a_broken_plugin_is_reported_and_skipped(self):
        """A third-party file must not be able to stop the receipt building."""
        self._write("broken.py", BROKEN_PLUGIN)
        self._write("linear.py", PLUGIN)
        ex = load_extract()
        self.assertIn("linear", {s.name for s in ex.registry()},
                      "a good plugin should still load alongside a broken one")
        data = ex.build(DAY)
        self.assertTrue(any("broken.py" in p for p in data["source_problems"]))

    def test_underscore_files_are_ignored(self):
        self._write("_helper.py", "raise RuntimeError('should never be imported')")
        ex = load_extract()
        self.assertEqual(ex.build(DAY)["source_problems"], [])

    def test_missing_plugin_dir_is_fine(self):
        os.environ["EOD_SOURCE_DIR"] = os.path.join(self.dir, "nope")
        ex = load_extract()
        self.assertEqual(ex.build(DAY)["source_problems"], [])


class TestPluginsInTheDay(TranscriptCase, PluginCase):
    def setUp(self):
        PluginCase.setUp(self)
        TranscriptCase.setUp(self)

    def tearDown(self):
        TranscriptCase.tearDown(self)
        PluginCase.tearDown(self)

    def test_plugin_items_reach_the_day(self):
        self._write("linear.py", PLUGIN)
        ex = load_extract()
        ex.ROOT = self.claude
        ex.CODEX_ROOT = self.codex
        data = ex.build(DAY)
        self.assertEqual(data["extra"].get("linear_issues"),
                         [{"id": "ENG-1", "title": "closed the flaky test"}],
                         "a plugin's own field must survive into the day")
        self.assertNotIn("linear_issues", data,
                         "plugin fields belong under extra, not the top level")

    def test_a_failing_source_surfaces_on_the_day(self):
        self._write("boom.py", FAILING_SOURCE)
        ex = load_extract()
        ex.ROOT = self.claude
        ex.CODEX_ROOT = self.codex
        data = ex.build(DAY)
        self.assertTrue(any("exploding" in p and "credential expired" in p
                            for p in data["source_problems"]),
                        "a configured source that failed must be visible")

    def test_an_unavailable_source_stays_quiet(self):
        self._write("quiet.py", UNAVAILABLE_SOURCE)
        ex = load_extract()
        ex.ROOT = self.claude
        ex.CODEX_ROOT = self.codex
        data = ex.build(DAY)
        self.assertEqual(data["source_problems"], [],
                         "not being set up is not a problem to report")


if __name__ == "__main__":
    unittest.main()
