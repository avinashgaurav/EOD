"""The entry point, exercised the way it is actually installed.

~/.hammerspoon/extract.py is commonly a symlink into a checkout rather than a
copy, and eod.lua invokes it by absolute path from whatever cwd Hammerspoon
happens to have. Those two facts together are what the package split could
plausibly have broken, and no unit test would have noticed: the modules import
fine, it is only the entry point that cannot find them.

The symlink case very nearly did break. The shim resolved its own directory with
abspath, which points at the symlink rather than at the checkout, so the eod
package was not beside it. It worked anyway only because Python resolves
sys.path[0] for a symlinked script, which is luck rather than design.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACT = os.path.join(ROOT_DIR, "extract.py")
CLI = os.path.join(ROOT_DIR, "bin", "eod")
DAY = "2026-08-06"


def run(args, cwd):
    return subprocess.run([sys.executable] + args, cwd=cwd,
                          capture_output=True, text=True, timeout=300)


class TestEntryPoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="eod-entry-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_runs_by_absolute_path_from_an_unrelated_cwd(self):
        r = run([EXTRACT, "--date", DAY], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])

    def test_runs_through_a_symlink(self):
        """How it is actually installed. The package lives beside the real file,
        not beside the link."""
        link_dir = os.path.join(self.tmp, "hammerspoon")
        os.makedirs(link_dir)
        link = os.path.join(link_dir, "extract.py")
        os.symlink(EXTRACT, link)
        r = run([link, "--date", DAY], cwd="/")
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertNotIn("ModuleNotFoundError", r.stderr)

    def test_shim_resolves_the_checkout_not_the_symlink(self):
        """The property directly, so this keeps holding even if a future Python
        stops resolving sys.path[0] for us."""
        link_dir = os.path.join(self.tmp, "hammerspoon")
        os.makedirs(link_dir)
        link = os.path.join(link_dir, "extract.py")
        os.symlink(EXTRACT, link)
        probe = ("import runpy, sys, os\n"
                 "sys.argv = ['extract.py', '--date', '%s']\n"
                 "src = open(%r).read().split('if __name__')[0]\n"
                 "ns = {'__file__': %r, '__name__': 'shim'}\n"
                 "exec(compile(src, %r, 'exec'), ns)\n"
                 "import eod.config\n"
                 "print(os.path.dirname(os.path.dirname(eod.config.__file__)))\n"
                 % (DAY, link, link, link))
        p = os.path.join(self.tmp, "probe.py")
        with open(p, "w") as f:
            f.write(probe)
        r = run([p], cwd="/")
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(r.stdout.strip(), os.path.realpath(ROOT_DIR),
                         "the shim must find the package beside the real file")

    def test_cache_lands_beside_the_real_file(self):
        """eod.lua reads cache/ relative to the checkout. If a symlinked install
        wrote somewhere else, the widget would show a stale receipt forever."""
        link_dir = os.path.join(self.tmp, "hammerspoon")
        os.makedirs(link_dir)
        os.symlink(EXTRACT, os.path.join(link_dir, "extract.py"))
        r = run([os.path.join(link_dir, "extract.py"), "--date", DAY], cwd="/")
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertIn(os.path.realpath(ROOT_DIR), r.stdout,
                      "engine should report a path inside the checkout")
        self.assertFalse(os.path.exists(os.path.join(link_dir, "cache")),
                         "nothing should be written beside the symlink")


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="eod-cli-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sources_runs_from_anywhere(self):
        r = run([CLI, "sources"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertIn("SOURCE", r.stdout)

    def test_cli_runs_through_a_symlink(self):
        link = os.path.join(self.tmp, "eod")
        os.symlink(CLI, link)
        r = run([link, "sources"], cwd="/")
        self.assertEqual(r.returncode, 0, r.stderr[-800:])

    def test_payload_prints_and_sends_nothing(self):
        r = run([CLI, "payload", "--date", DAY], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertIn("Nothing is being sent now", r.stderr)

    def test_no_subcommand_prints_help_and_fails(self):
        r = run([CLI], cwd=self.tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("usage", r.stdout.lower())


if __name__ == "__main__":
    unittest.main()
